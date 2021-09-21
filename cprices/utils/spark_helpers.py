"""A selection of helper functions for building in pyspark."""
from collections import abc
import functools
import itertools
from typing import (
    Any,
    Callable,
    Iterable,
    List,
    Mapping,
    Optional,
    Sequence,
    Set,
    Tuple,
    Union,
)
import warnings

import docrep
import pandas as pd
from py4j.protocol import Py4JError
from pyspark.sql import (
    Column as SparkCol,
    DataFrame as SparkDF,
    functions as F,
    Window,
    WindowSpec,
)

from .helpers import list_convert


docstrings = docrep.DocstringProcessor()
Key = Sequence[Union[str, Sequence[str]]]

# The order of these is important, big ---> small.
SPARK_NUMBER_TYPES = (
    'decimal(10,0)',
    'double',
    'float',
    'bigint',
    'int',
    'smallint',
    'tinyint',
)


def to_spark_col(_func=None, *, exclude: Sequence[str] = None) -> Callable:
    """Convert str args to Spark Column if not already."""
    if not exclude:
        exclude = []

    def caller(func: Callable[[Union[str, SparkCol]], SparkCol]):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            varnames = func.__code__.co_varnames
            if args:
                args = [
                    _convert_to_spark_col(arg)
                    if varnames[i] not in exclude
                    else arg
                    for i, arg in enumerate(args)
                ]
            if kwargs:
                kwargs = {
                    k: _convert_to_spark_col(kwarg)
                    if k not in exclude
                    else kwarg
                    for k, kwarg in kwargs.items()
                }
            return func(*args, **kwargs)
        return wrapper

    if _func is None:
        return caller
    else:
        return caller(_func)


def _convert_to_spark_col(s: Any) -> Union[Any, SparkCol]:
    """Convert strings to Spark Columns, otherwise returns input."""
    try:
        return F.col(s)
    except (AttributeError, Py4JError):
        return s


def map_col(col_name: str, mapping: Mapping[Any, Any]) -> SparkCol:
    """Map PySpark column using Python mapping."""
    map_expr = F.create_map([
        F.lit(x)
        if not is_list_or_tuple(x)
        # To handle when the value is a list or tuple.
        else F.array([F.lit(i) for i in x])
        # Convert mapping to list.
        for x in itertools.chain(*mapping.items())
    ])
    return map_expr[F.col(col_name)]


@docstrings.get_sections(base='concat')
def concat(
    frames: Union[Iterable[SparkDF], Mapping[Key, SparkDF]],
    keys: Optional[Key] = None,
    names: Optional[Union[str, Sequence[str]]] = None,
) -> SparkDF:
    """
    Concatenate pyspark DataFrames with additional key columns.

    Will attempt to cast column data types where schemas are mismatched
    and fill empty columns with Nulls:

    * upcasts to largest number data type present (for that column)
    * casts to string if there is at least one dtype of 'string' for a
      given column

    Parameters
    ----------
    frames : a sequence or mapping of SparkDF
        If a mapping is passed, then the sorted keys will be used as the
        `keys` argument, unless it is passed, in which case the values
        will be selected.
    keys : a sequence of str or str sequences, optional
        The keys to differentiate child dataframes in the concatenated
        dataframe. Each key can have multiple parts but each key should
        have an equal number of parts. The length of `names` should be
        equal to the number of parts. Keys must be passed if `frames` is
        a sequence.
    names : str or list of str, optional
        The name or names to give each new key column. Must match the
        size of each key.

    Returns
    -------
    SparkDF
        A single DataFrame combining the given frames with a
        ``unionByName()`` call. The resulting DataFrame has new columns
        for each given name, that contains the keys which identify the
        child frames.

    Notes
    -----
    This code is mostly adapted from :func:`pandas.concat`.
    """
    if isinstance(frames, (SparkDF, str)):
        raise TypeError(
            "first argument must be an iterable of pyspark DataFrames,"
            f" you passed an object of type '{type(frames)}'"
        )

    if len(frames) == 0:
        raise ValueError("No objects to concatenate")

    if isinstance(frames, abc.Sequence):
        if keys and (len(frames) != len(keys)):
            raise ValueError(
                "keys must be same length as frames"
                " when frames is a list or tuple"
            )

    if isinstance(frames, abc.Mapping):
        if names is None:
            raise ValueError(
                "when the first argument is a mapping,"
                " the names argument must be given"
            )
        if keys is None:
            keys = list(frames.keys())
        # If keys are passed with a mapping, then the mapping is subset
        # using the keys. This also ensures the order is correct.
        frames = [frames[k] for k in keys]
    else:
        frames = list(frames)

    col_schemas = set()
    for frame in frames:
        if not isinstance(frame, SparkDF):
            raise TypeError(
                f"cannot concatenate object of type '{type(frame)}'; "
                "only pyspark.sql.DataFrame objs are valid"
            )
        # Get a set of all column schemas (name, type) across frames.
        col_schemas.update(frame.dtypes)

    schemas_are_equal = _compare_schemas(frames, keys, names)

    # Allows dataframes with inconsistent schemas to be concatenated by
    # filling empty columns with Nulls and casting some column data
    # types where appropriate.
    #
    # Potentially remove when Spark 3.1.0 available.
    if not schemas_are_equal:
        frames = [
            _ensure_consistent_schema(frame, col_schemas)
            for frame in frames
        ]

    # Potentially update with commented line when Spark 3.1.0 available.
    # union = functools.partial(SparkDF.unionByName, allowMissingColumns=True)
    union = SparkDF.unionByName

    # If no keys or names are given then simply union the DataFrames.
    if not names and not keys:
        return functools.reduce(union, frames)

    # Convert names and keys elements to a list if not already, so they
    # can be iterated over in the next step.
    names = list_convert(names)
    keys = [list_convert(key) for key in keys]

    if not all([len(key) == len(names) for key in keys]):
        raise ValueError(
            "the length of each key must equal the length of names"
        )
    if not all([len(key) == len(keys[0]) for key in keys]):
        raise ValueError(
            "all keys must be of equal length"
        )

    frames_to_concat = []
    # Loop through each frame, and add each part in the keys to a new
    # column defined by name.
    for parts, frame in zip(keys, frames):
        for name, part in reversed(tuple(zip(names, parts))):
            frame = frame.select(F.lit(part).alias(name), '*')
        frames_to_concat.append(frame)

    return functools.reduce(union, frames_to_concat)


def is_list_or_tuple(x):
    """Return True if list or tuple."""
    return isinstance(x, tuple) or isinstance(x, list)


def get_window_spec(levels: Sequence[str] = None) -> WindowSpec:
    """Return WindowSpec partitioned by levels, defaulting to whole df."""
    if not levels:
        return whole_frame_window()
    else:
        return Window.partitionBy(levels)


def whole_frame_window() -> WindowSpec:
    """Return WindowSpec for whole DataFrame."""
    return Window.rowsBetween(
        Window.unboundedPreceding,
        Window.unboundedFollowing,
    )


def to_list(df: SparkDF) -> List[Union[Any, List[Any]]]:
    """Convert Spark DF to a list.

    Returns
    -------
    list or list of lists
        If the input DataFrame has a single column then a list of column
        values will be returned. If the DataFrame has multiple columns
        then a list of row data as lists will be returned.
    """
    if len(df.columns) == 1:
        return df.toPandas().squeeze().tolist()
    else:
        return df.toPandas().values.tolist()


def map_column_names(df: SparkDF, mapper: Mapping[str, str]) -> SparkDF:
    """Map column names to the given values in the mapper.

    If the column name is not in the mapper the name doesn't change.
    """
    cols = [
        F.col(col_name).alias(mapper.get(col_name, col_name))
        for col_name in df.columns
    ]
    return df.select(*cols)


def get_hive_table_columns(spark, table_path) -> List[str]:
    """Return the column names for the given Hive table."""
    return to_list(spark.sql(f'SHOW columns in {table_path}'))


def transform(self, f, *args, **kwargs):
    """Chain Pyspark function."""
    return f(self, *args, **kwargs)


def _ensure_consistent_schema(
    frame: SparkDF,
    column_schemas: Set[Tuple[str, str]],
) -> SparkDF:
    """Ensure the dataframe is consistent with the schema.

    If there are column data type mismatches, (more than one data type
    for a column name in the column schemas) then will try to convert
    the data type if possible:

    * if they are all number data types, then picks the largest number
      type present
    * if one of the types is string, then ensures it casts the column to
      string type

    Also fills any missing columns with Null values, ensuring correct
    dtype.

    Parameters
    ----------
    frame : SparkDF
    column_schemas : set
        A set of simple column schemas in the form (name, dtype) for all
        dataframes set to be concatenated.

    Returns
    -------
    SparkDF
        Input dataframe with consistent schema.
    """
    for column, dtype in column_schemas-set(frame.dtypes):
        # Check for multiple dtypes in the column schemas for each
        # column name.
        col_dtypes = _get_column_types(column_schemas, column)

        if len(col_dtypes) > 1:
            # If multiple number dtypes, then cast all columns of
            # same name to largest number dtype present.
            if _are_all_number_types(col_dtypes):
                dtype = _get_largest_number_dtype(col_dtypes)
            # If multiple dtypes and string dtype present, then cast
            # all columns of same name to string dtype.
            elif any(dtype == 'string' for dtype in col_dtypes):
                dtype = 'string'
            else:
                raise TypeError(
                    "Spark column data type mismatch for column:"
                    f" '{column}'. Can't auto-convert between types"
                    f" {col_dtypes}."
                )

        # If current frame missing the column in the schema, then
        # set values to Null.
        vals = (
            F.lit(None) if column not in frame.columns
            else F.col(column)
        )
        # Cast the values with the correct dtype.
        frame = frame.withColumn(column, vals.cast(dtype))

    return frame


def _get_column_types(
    column_schemas: Sequence[Tuple[str, str]],
    column_name: str,
) -> Set[str]:
    """Return a set of all data types present for a given column name.

    Parameters
    ----------
    column_schemas
        A sequence of simple column schemas in the form (name, dtype).
    column_name
        The column name to match on in the sequence of column schemas.

    Returns
    -------
    set
        A set of all dtypes present in the column_schemas for a given
        column name.
    """
    return {
        dtype for name, dtype in column_schemas
        if name == column_name
    }


def _are_all_number_types(dtypes: Sequence[str]) -> bool:
    """Return True if all dtypes are Spark number data types."""
    return all(dtype in SPARK_NUMBER_TYPES for dtype in dtypes)


def _get_largest_number_dtype(dtypes: Sequence[str]) -> str:
    """Return the largest Spark number data type in the input."""
    return next((
        dtype for dtype in SPARK_NUMBER_TYPES
        if dtype in dtypes
    ))


def _compare_schemas(
    frames: Sequence[pd.DataFrame],
    keys: Optional[Key] = None,
    names: Optional[Union[str, Sequence[str]]] = None,
) -> bool:
    """Return True if schemas are equal, else throw warning.

    If unequal, throws a warning that displays the schemas for all the
    unequal columns.

    Parameters
    ----------
    %(concat.parameters)s

    Returns
    -------
    True if column schemas are equal, else False.
    """
    schemas_df = _get_schemas_df(frames, keys, names)

    equal_schemas = (
        schemas_df
        .apply(lambda col: col == schemas_df.iloc[:, 0])
        .all(axis=1)
    )

    if not equal_schemas.all():
        warnings.warn(
            "column dtypes in the schemas are not equal, attempting to coerce"
            f"\n\n{str(schemas_df.loc[~equal_schemas])}",
            UnequalSchemaWarning,
        )
        return False
    else:
        return True


def _get_schemas_df(
    frames: Sequence[pd.DataFrame],
    keys: Optional[Key] = None,
    names: Optional[Union[str, Sequence[str]]] = None,
) -> pd.DataFrame:
    """
    Return dataframe of column schemas for given frames.

    Parameters
    ----------
    %(concat.parameters)s

    Returns
    -------
    pandas DataFrame
        The dtypes for each frame in each column of data, with column
        names in the index. If names (and optionally keys) given, then
        columns renamed to identify each frame. Otherwise columns are
        named dtype_{i} where i is the position of the frame in the
        sequence.
    """
    schemas_df = pd.DataFrame()
    for df in frames:
        col_names, dtypes = zip(*df.dtypes)
        schema = pd.Series(dtypes, index=col_names)
        schemas_df = pd.concat([schemas_df, schema], axis=1)

    if keys:
        schemas_df.columns = pd.MultiIndex.from_tuples(keys, names=names)
    else:
        schemas_df.columns = [f'dtype_{i+1}' for i in range(len(frames))]

    return schemas_df


class UnequalSchemaWarning(Warning):
    pass

"""A selection of helper functions for building in pyspark."""
from collections import abc
import functools
import itertools
from typing import (
    Callable,
    List,
    Mapping,
    Any,
    Sequence,
    Union,
    Iterable,
    Optional,
)

from py4j.protocol import Py4JError
from pyspark.sql import (
    Column as SparkCol,
    DataFrame as SparkDF,
    functions as F,
    Window,
    WindowSpec,
)
from pyspark.sql.functions import lit, create_map, col, array


Key = Sequence[Union[str, Sequence[str]]]


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
        return col(s)
    except (AttributeError, Py4JError):
        return s


def map_col(col_name: str, mapping: Mapping[Any, Any]) -> SparkCol:
    """Map PySpark column using Python mapping."""
    map_expr = create_map([
        lit(x)
        if not is_list_or_tuple(x)
        # To handle when the value is a list or tuple.
        else array([lit(i) for i in x])
        # Convert mapping to list.
        for x in itertools.chain(*mapping.items())
    ])
    return map_expr[col(col_name)]


def concat(
    frames: Union[Iterable[SparkDF], Mapping[Key, SparkDF]],
    names: Union[str, Sequence[str]],
    keys: Optional[Key] = None,
) -> SparkDF:
    """
    Concatenate pyspark DataFrames with additional key columns.

    Parameters
    ----------
    frames : a sequence or mapping of SparkDF
        If a mapping is passed, then the sorted keys will be used as the
        `keys` argument, unless it is passed, in which case the values
        will be selected.
    names : str or list of str
        The name or names to give each new key column. Must match the
        size of each key.
    keys : a sequence of str or str sequences, optional
        The keys to differentiate child dataframes in the concatenated
        dataframe. Each key can have multiple parts but each key should
        have an equal number of parts. The length of `names` should be
        equal to the number of parts. Keys must be passed if `frames` is
        a sequence.

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
        if keys is None:
            raise ValueError(
                "keys must be passed if frames is a list or tuple"
            )
        else:
            if len(frames) != len(keys):
                raise ValueError(
                    "keys must be same length as frames"
                    " when frames is a list or tuple"
                )

    if isinstance(frames, abc.Mapping):
        if keys is None:
            keys = list(frames.keys())
        # If keys are passed with a mapping, then the mapping is subset
        # using the keys. This also ensures the order is correct.
        frames = [frames[k] for k in keys]
    else:
        frames = list(frames)

    for frame in frames:
        if not isinstance(frame, SparkDF):
            TypeError(
                f"cannot concatenate object of type '{type(frame)}'; "
                "only pyspark.sql.DataFrame objs are valid"
            )

    # Convert names an keys elements to a list if not already, so they
    # can be iterated over in the next step.
    names = _list_convert(names)
    keys = [_list_convert(key) for key in keys]

    if not all([len(key) == len(names) for key in keys]):
        raise ValueError(
            "the length of each key must equal the length of names"
        )

    frames_to_concat = []
    # Loop through each frame, and add each part in the keys to a new
    # column defined by name.
    for parts, frame in zip(keys, frames):
        for name, part in zip(names, parts):
            frame = frame.withColumn(name, F.lit(part))
        frames_to_concat.append(frame)

    return functools.reduce(SparkDF.unionByName, frames_to_concat)


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


def _list_convert(x: Any) -> List[Any]:
    """Return obj as a single item list if not already a list or tuple."""
    return [x] if not (isinstance(x, list) or isinstance(x, tuple)) else x

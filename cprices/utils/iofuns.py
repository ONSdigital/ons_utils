"""I/O functions for pipeline interaction with HDFS."""
# import python libraries
import copy
from datetime import datetime
import logging
import os
from typing import Dict

# import pyspark libraries
from pyspark.sql import DataFrame as sparkDF
from pyspark.sql import SparkSession


LOGGER = logging.getLogger()


def load_input_data(
    spark: SparkSession,
    input_data: dict,
    staged_dir: str,
    scanner_data_columns: list,
    scanner_input_tables: dict,
) -> Dict[dict, sparkDF]:
    """Load data for processing as specified in the scenario config.

    Parameters
    ----------
    spark
        Spark session.

    input_data
        Dictionary with all the data sources, suppliers and items. Each
        combination is a path of dictionary keys that lead to a value. This is
        initialised as an empty dictionary {}.
    staged_dir
        The path to the HDFS directory from where the staged webscraped data
        is located.
    scanner_data_columns
        List of columns to be loaded in.
    scanner_input_tables
        Dictionary to map the supplier to a HIVE table path.

    Returns
    -------
    Dict[dict, sparkDF]
        Each path of keys leads to a value/spark dataframe as it was read
        from HDFS for the corresponding table.
        from HDFS for the corresponding table.
    """
    # Create a full copy of the input_data dictionary
    staged_data = copy.deepcopy(input_data)

    for data_source in input_data:

        # webscraped data has 3 levels: data_source, supplier, item
        if data_source == 'web_scraped':
            for supplier in input_data[data_source]:
                for item in input_data[data_source][supplier]:
                    path = os.path.join(
                        staged_dir,
                        data_source,
                        supplier,
                        item+'.parquet'
                    )

                    staged_data[data_source][supplier][item] = (
                        spark
                        .read
                        .parquet(path)
                    )

        # conventional and scanner data have 2 levels: data_source, supplier
        elif data_source == 'scanner':
            for supplier in input_data[data_source]:
                path = scanner_input_tables.get(supplier)

                staged_data[data_source][supplier] = spark.sql(
                    f"SELECT {','.join(scanner_data_columns)} FROM {path}"
                )

        elif data_source == 'conventional':
            # Currently only single supplier (local_collection) and file
            # (historic) available for conventional data
            path = os.path.join(
                staged_dir,
                data_source,
                'local_collection',
                'historic_201701_202001.parquet'
            )

            staged_data[data_source] = spark.read.parquet(path)

    return staged_data


def save_output_hdfs(
    dfs: Dict[str, sparkDF],
    processed_dir: str,
) -> str:
    """Store output dataframes (combined across all scenarios) in HDFS.

    Parameters
    ----------
    dfs
        The output dataframes from all scenarios to store in HDFS.
    processed_dir
        It has the path to the HDFS directory where the dfs will be stored.

    Returns
    -------
    str
        The unique identifying string for the run, of the form
        current date, time and username (YYYYMMDD_HHMMSS_username).

    Notes
    -----
    Run_id is the name of the folder that will be created inside the processed
    data folder in HDFS for this particular run and will contain all the
    output dataframes. The run_id is printed on the screen for the user to
    explore the output data.

    The configuration dataset is a two-column table where the first column
    shows the stage of the core pipeline and the second column shows (as a
    dictionary) all the config parameters for the corresponding stage. This
    can be used as a reference for the user in case they want to check the
    configuration of this run.
    """
    # create run id using username and current time
    username = os.environ['HADOOP_USER_NAME']
    current_date_time = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_id = '_'.join([current_date_time, username])

    # create directory path to export processed data
    processed_dir = os.path.join(processed_dir, run_id)

    for name in dfs:
        LOGGER.info(f'{name}...')
        if name in ['analysis']:
            # store analysis output as csv
            path = os.path.join(processed_dir, 'analysis')
            dfs[name].repartition(1).write.csv(
                path,
                header=True,
                mode='overwrite'
            )

        else:
            path = os.path.join(processed_dir, name)
            dfs[name].write.parquet(path)

    return run_id

"""Validation rules for config files."""
from typing import Any, Dict, Callable, Sequence

from cerberus import Validator

from epds_utils import hdfs


class ScenarioSectionError(Exception):
    """Exception raised when sections are missing in the config.name file."""

    def __init__(self, config, section):
        """Init the ScenarioSectionError."""
        self.message = (
            f"{config.name}: {section} does not appear"
            " among the config parameters."
        )
        super().__init__(self.message)


def validators_lib() -> Dict[str, Callable]:
    """Return a dict of validation functions for each section."""
    return {
        'preprocessing': validate_preprocessing,
        'consumptions_segments_mappers': validate_classification,
        'outlier_detection': validate_outlier_detection,
        'averaging': validate_averaging,
        'grouping': validate_grouping,
        'flag_low_expenditures': validate_flag_low_expenditures,
        'indices': validate_indices,
    }


def check_config_sections_exist(config, sections) -> None:
    """Validate that all sections are in the given config."""
    for key in sections:
        if key not in vars(config).keys():
            raise ScenarioSectionError(config.name, key)


def validate_section_values(config, sections: Sequence[str]):
    """Validate the given sections with the appropriate validator."""
    validators = validators_lib()
    for section in sections:
        validator = validators.get(section)
        validator(config)


def validate_conventional_scenario_sections(config) -> None:
    """Validate the sections in the conventional scenario config."""
    required_sections = ['input_data']
    check_config_sections_exist(config, required_sections)


def validate_scan_scenario_config(config) -> None:
    """Validate the config using required sections for scanner."""
    required_sections = [
        'input_data',
        'preprocessing',
        'consumption_segment_mappers',
        'outlier_detection',
        'averaging',
        'flag_low_expenditures',
        'indices'
    ]
    check_config_sections_exist(config, required_sections)
    validate_section_values(config, required_sections)


def validate_webscraped_scenario_config(config) -> None:
    """Validate the config using required sections for web scraped."""
    required_sections = [
        'input_data',
        'consumption_segment_mappers',
        'outlier_detection',
        'averaging',
        'grouping'
        'indices'
    ]
    check_config_sections_exist(config, required_sections)
    validate_section_values(config, required_sections)


def validate_non_section_values(config) -> None:
    """Validate the generic input settings in the config."""
    v = Validator()
    v.schema = {
        'start_date': {
            'type': 'date',
            'regex': r'([12]\d{3}-(0[1-9]|1[0-2])-01)',
        },
        'end_date': {
            'type': 'date',
            'regex': r'([12]\d{3}-(0[1-9]|1[0-2])-01)',
        },
        'extra_strata': {
            'type': ['list', 'string'],
        }
    }

    if not v.validate({'start_date': config.start_date}):
        raise ValueError(
            f"{config.name}: parameter 'start_date'"
            " must be a string in the format YYYY-MM-01."
        )

    if not v.validate({'end_date': config.end_date}):
        raise ValueError(
            f"{config.name}: parameter 'end_date'"
            " must be a string in the format YYYY-MM-01."
        )

    if config.extra_strata:
        if not v.validate({'extra_strata': config.extra_strata}):
            raise ValueError(
                f"{config.name}: parameter 'extra_strata'"
                " must be a string or list of strings."
            )


def validate_preprocessing(config) -> None:
    """Validate the preprocessing settings in the config."""
    expenditure_cols = {
        'sales_value_inc_discounts',
        'sales_value_exc_discounts',
        'sales_value_vat',
        'sales_value_vat_exc_discounts',
    }

    v = Validator()
    v.schema = {
        'use_unit_prices': {'type': 'boolean'},
        'product_id_code_col': {
            'type': 'string',
            'allowed': ['gtin', 'productid_ons', 'sku'],
        },
        'calc_price_before_discount': {'type': 'boolean'},
        'promo_col': {
            'type': 'string',
            'allowed': ['price_promo_discount', 'multi_promo_discount'],
        },
        'sales_value_col': {
            'type': 'string',
            'allowed': expenditure_cols,
        },
        'align_daily_frequency': {
            'type': 'string',
            'allowed': ['weekly', 'monthly'],
        },
        'week_selection': {
            'type': 'list',
            'allowed': [1, 2, 3, 4],
            'nullable': True,
        },
    }

    single_selection_checks = {
        'product_id_code_col',
        'promo_col',
        'sales_value_col',
        'align_daily_frequency',
    }

    type_checks = {
        'use_unit_prices',
        'calc_price_before_discount',
    }

    multiple_selection_checks = {
        'week_selection',
    }

    for param in v.schema:
        to_validate = config.preprocessing[param]
        if not v.validate({param: to_validate}):
            err = ValidationErrors(config.name)

            if param in single_selection_checks:
                err.selection_single_error(
                    param,
                    allowed=v.schema.get(param).get('allowed'),
                    actual=to_validate,
                    section='preprocessing',
                )
            elif param in multiple_selection_checks:
                err.selection_multiple_error(
                    param,
                    allowed=v.schema.get(param).get('allowed'),
                    actual=to_validate,
                    section='preprocessing',
                )
            elif param in type_checks:
                err.bool_error(
                    param,
                    actual=to_validate,
                    section='preprocessing',
                )


class ConfigValueError(ValueError):
    pass


class ValidationErrors:
    """A class to print various error messages for Validation."""

    def __init__(self, name: str):
        """Init the class."""
        self.name = name

    def selection_single_error(
        self,
        parameter: str,
        allowed: Any,
        actual: Any,
        section: str = None,
    ) -> None:
        """Error for a non-list type with "allowed" check."""
        must_str = f"must be one of : {allowed}."
        msg = self._main_msg(parameter, actual, must_str, section)

        raise ConfigValueError(msg)

    def selection_multiple_error(
        self,
        parameter: str,
        allowed: Any,
        actual: Any,
        section: str = None,
    ) -> None:
        """Error for a list type with "allowed" check."""
        must_str = f"must be one or more of : {allowed}."
        msg = self._main_msg(parameter, actual, must_str, section)

        raise ConfigValueError(msg)

    def bool_error(
        self,
        parameter: str,
        actual: Any,
        section: str = None,
    ) -> None:
        """Raise an error for the boolean check."""
        must_str = "must be a boolean value."
        msg = self._main_msg(parameter, actual, must_str, section)

        raise ConfigValueError(msg)

    def _main_msg(
        self,
        parameter: str,
        actual: Any,
        must_str: str,
        section: str = None,
    ):
        """Construct the main error message."""
        msg = []
        msg.append(f"{self.name}: parameter {parameter}")
        if section:
            msg.append(f"in {section}")
        msg.append(must_str)
        msg.append(f"Instead got {actual}.")

        return " ".join(msg)


def validate_classification(config) -> None:
    """Validate the classification settings in the config."""
    mappers = config.consumption_segment_mappers
    for data_source, d1 in mappers.items():
        for level, d2 in d1.items():
            if data_source == 'scanner':
                validate_mapper_paths(d2, data_source, level)

            if data_source == 'web_scraped':
                for item, path in d2.items():
                    scenario = f'{level}, {item}'
                    validate_mapper_paths(path, data_source, scenario)


def validate_mapper_paths(
    path: str,
    data_source: str,
    level: str,
) -> None:
    """Validate the item mappers exist in hdfs."""
    if not hdfs.test(path):
        raise Exception(
            f"{data_source}: {level} user defined mapper"
            f" {path} does not exist."
        )


def validate_outlier_detection(config):
    """Validate the outlier detection settings in the config."""
    outlier_methods = {'tukey', 'kimber', 'ksigma'}

    v = Validator()
    v.schema = {
        # Outlier detection/ Averaging/ Grouping/ Filtering/ Imputation
        'active': {'type': 'boolean'},
        'log_transform': {'type': 'boolean'},
        'outlier_methods': {
            'type': 'string',
            'allowed': outlier_methods
        },
        'k': {
            'type': 'float',
            'min': 1,
            'max': 4,
        },
        'fence_value': {'type': 'float'},
        'stddev_method': {
            'type': 'string',
            'allowed': ['population', 'sample'],
        },
        'quartile_method': {
            'type': 'string',
            'allowed': ['exact', 'approx'],
        },
        'accuracy': {
            'type': 'float',
            'min': 1,
        },
    }

    active = config.outlier_detection['active']
    if not v.validate({'active': active}):
        raise ValueError(
            f"{config.name}: parameter 'active' in outlier_detection"
            " must be a boolean."
            f" Instead got '{active}'."
        )

    # If active is True, validate the rest.
    if active:
        to_validate = config.outlier_detection['options']['log_transform']
        if not v.validate({'log_transform': to_validate}):
            raise ValueError(
                f"{config.name}: parameter 'log_transform' in"
                " outlier_detection must be a boolean."
                f" Instead got '{to_validate}'."
            )

        to_validate = config.outlier_detection['options']['method']
        if not v.validate({'outlier_methods': to_validate}):
            raise ValueError(
                f"{config.name}: parameter 'method' for outlier detection"
                f" must be one of {outlier_methods}."
                f" Instead got '{to_validate}'."
            )

        to_validate = config.outlier_detection['options']['k']
        if not v.validate({'k': to_validate}):
            raise ValueError(
                f"{config.name}: parameter 'k' for outlier detection"
                " must be a float between 1 and 4."
                f" Instead got '{to_validate}'."
            )

        to_validate = config.outlier_detection['options']['stddev_method']
        if not v.validate({'stddev_method': to_validate}):
            raise ValueError(
                f"{config.name}: parameter 'stddev_method' for outlier"
                " detection must be one of {'population', 'sample'}."
                f" Instead got '{to_validate}'."
            )

        to_validate = config.outlier_detection['options']['quartile_method']
        if not v.validate({'quartile_method': to_validate}):
            raise ValueError(
                f"{config.name}: parameter 'quartile_method' for outlier"
                " detection must be one of {'exact', 'approx'}."
                f" Instead got '{to_validate}'."
            )

        to_validate = config.outlier_detection['options']['accuracy']
        if not v.validate({'accuracy': to_validate}):
            raise ValueError(
                f"{config.name}: parameter 'accuracy' for outlier"
                " detection must be a positive numeric literal."
                f" Instead got '{to_validate}'."
            )


def validate_grouping(config):
    """ """
    pass


def validate_averaging(config):
    """Validate the averaging settings in the config."""
    averaging_methods = {
        'unweighted_arithmetic',
        'unweighted_geometric',
        'weighted_arithmetic',
        'weighted_geometric'
    }
    v = Validator()
    v.schema = {
        'active': {'type': 'boolean'},
        'method': {
            'type': 'string',
            'allowed': averaging_methods,
        },
    }

    active = config.averaging['active']
    if not v.validate({'active': active}):
        raise ValueError(
            f"{config.name}: parameter 'active' in grouping"
            " must be a boolean."
            f" Instead got '{active}'."
        )

    if active:
        to_validate = config.averaging['method']
        if not v.validate({'method': to_validate}):
            raise ValueError(
                f"{config.name}: method for averaging must"
                " be one of {averaging_methods}."
                f" Instead got '{to_validate}'."
            )


def validate_flag_low_expenditures(config):
    """Validate the flag_low_expenditures settings in the config."""
    v = Validator()
    v.schema = {
        'active': {'type': 'boolean'},
        'threshold': {
            'type': 'float',
            'min': 0,
            'max': 1,
        },
    }

    active = config.flag_low_expenditures['active']
    if not v.validate({'active': active}):
        raise ValueError(
            f"{config.name}: parameter 'active' in flag_low_expenditures"
            " must be a boolean."
            f" Instead got '{active}'."
        )

    if active:
        to_validate = config.flag_low_expenditures['threshold']
        if not v.validate({'threshold': to_validate}):
            raise ValueError(
                f"{config.name}: threshold in flag_low_expenditures"
                " must be a float between 0 and 1."
                f" Instead got '{to_validate}'."
            )


def validate_indices(config):
    """Validate the indices settings in the config."""
    base_price_methods = {
        'fixed_base',
        'chained',
        'bilateral',
        'fixed_base_with_rebase',
    }

    index_methods = {
        'carli',
        'jevons',
        'dutot',
        'laspeyres',
        'paasche',
        'fisher',
        'tornqvist',
        'geary-khamis',
    }

    multilateral_methods = {
        'ewgeks',
        'rygeks',
        'geks_movement_splice',
        'geks_window_splice',
        'geks_half_window_splice',
        'geks_december_link_splice',
        'geks_mean_splice',
    }

    v = Validator()
    v.schema = {
        'base_price_methods': {
            'type': 'list',
            'allowed': base_price_methods,
            'nullable': True,
        },
        'index_methods': {
            'type': 'list',
            'allowed': index_methods,
        },
        'multilateral_methods': {
            'type': 'list',
            'allowed': multilateral_methods,
            'nullable': True,
        },
        'base_period': {
            'type': 'integer',
            'min': 1,
            'max': 12,
        },
        'window': {
            'type': 'integer',
            'min': 3,
        },
    }

    to_validate = config.indices['base_price_methods']
    if not v.validate({'base_price_methods': to_validate}):
        raise ValueError(
            f"{config.name}: parameter 'base_price_methods' in indices"
            f" must be a list containing values among {base_price_methods}."
            f" Instead got '{to_validate}'."
        )

    to_validate = config.indices['index_methods']
    if not v.validate({'index_methods': to_validate}):
        raise ValueError(
            f"{config.name}: parameter 'index_methods' in indices"
            " must be a list containing values among {index_methods}."
            f" Instead got '{to_validate}'."
        )

    to_validate = config.indices['multilateral_methods']
    if not v.validate({'multilateral_methods': to_validate}):
        raise ValueError(
            f"{config.name}: parameter 'multilateral_methods' in indices"
            " must be a list containing values among {multilateral_methods}."
            f" Instead got '{to_validate}'."
        )

    to_validate = config.indices['window']
    if not v.validate({'window': to_validate}):
        raise ValueError(
            f"{config.name}: parameter 'window' in indices"
            " must be a positive integer > 2."
            f" Instead got '{to_validate}'."
        )

    to_validate = config.indices['base_period']
    if not v.validate({'base_period': to_validate}):
        raise ValueError(
            f"{config.name}: parameter 'base_period' in indices"
            " must be an integer representing a month between 1"
            " and 12 inclusive."
            f" Instead got '{to_validate}'."
        )

    if not (
        config.indices['base_price_methods']
        or config.indices['multilateral_methods']
    ):
        raise ValueError(
            "One of either 'base_price_methods' or 'multilateral_methods'"
            " must be provided. They can't both be None."
        )

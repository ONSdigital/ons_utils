"""Tests for the config classes in config.py."""
import yaml
import pytest

from ons_utils.config.config import *
from ons_utils import config

from tests.conftest import (
    Case,
    parametrize_cases,
)


def write_config_yaml(
    dir,
    yaml_input: str = "my_attr: test",
    name: str = 'my_config',
) -> None:
    """Write a file called my_config.yaml with given yaml at given dir."""
    with open(dir.join(f'{name}.yaml'), 'w') as f:
        yaml.dump(yaml.safe_load(yaml_input), f)


@pytest.fixture
def test_config(tmpdir, monkeypatch):
    """Sets up a test config file in tmpdir/config with given yaml."""
    def _(
        yaml_input: str = "my_attr: test",
        name: str = 'my_config',
    ) -> Config:
        config_dir = (
            tmpdir.join('config') if tmpdir.join('config').check()
            else tmpdir.mkdir('config')
        )
        monkeypatch.setattr(config.Path, 'home', lambda: Path(tmpdir))
        write_config_yaml(config_dir, yaml_input, name)
        return Config(name)
    return _


class TestConfig:
    """Group of tests for Config."""

    def test_init_assigns_name_and_config_path_attrs(self, test_config, tmpdir):
        """Test that the name and config attributes are assigned after init."""
        # test_config creates a config file 'my_config.yaml' in the dir
        # tmpdir/config.
        conf = test_config()
        assert conf.name == 'my_config'
        assert conf.config_path == Path(tmpdir).joinpath('config', 'my_config.yaml')

    def test_get_config_dir_when_cprices_config_env_variable_set(
        self, tmpdir, monkeypatch
    ):
        """Patch the CPRICES_CONFIG env variable and assert get_config_dir method
        returns the locations given by the env var.
        """
        monkeypatch.setenv('CPRICES_CONFIG', str(tmpdir))
        write_config_yaml(tmpdir)
        conf = Config('my_config')
        assert conf.get_config_dir() == tmpdir

    def test_get_config_dir_returns_cprices_cprices_first_if_exists(
        self, tmpdir, monkeypatch,
    ):
        """Test that get_config_dir returns the config dir in the nested
        folder cprices/cprices ahead of returning a config dir in the current
        working directory or the home locations. This is how the current nesting
        is on DAP.
        """
        target_dir = tmpdir.mkdir('cprices').mkdir('cprices').mkdir('config')
        tmpdir.mkdir('config')

        monkeypatch.setattr(config.Path, 'cwd', lambda: Path(tmpdir))
        monkeypatch.setattr(config.Path, 'home', lambda: Path(tmpdir))

        write_config_yaml(target_dir)

        assert Config('my_config').get_config_dir() == target_dir

    def test_get_config_dir_returns_home_dir_config_if_no_cprices_dir(
        self, tmpdir, monkeypatch,
    ):
        """Test that get_config_dir returns home before current working directory."""
        target_dir = tmpdir.mkdir('config')

        monkeypatch.setattr(config.Path, 'cwd', lambda: Path(tmpdir))
        monkeypatch.setattr(config.Path, 'home', lambda: Path(tmpdir))

        write_config_yaml(target_dir)

        assert Config('my_config').get_config_dir() == target_dir

    def test_get_config_path(self, test_config, tmpdir):
        """Test get_config_path returns the path of the given config file."""
        # test_config creates a config file 'my_config.yaml' in the dir
        # tmpdir/config.
        conf = test_config()
        expected = Path(tmpdir).joinpath('config', 'my_config.yaml')
        assert conf.get_config_path() == expected

    def test_load_config(self, test_config):
        """Test load_config method loads YAML input and returns a dict."""
        conf = test_config(yaml_input="""
        bells:
            big_ben:
                dongs: 12
        whistles:
            - referee
            - dog
        """)

        assert conf.load_config() == {
            'bells': {'big_ben': {'dongs': 12}},
            'whistles': ['referee', 'dog'],
        }

    def test_raises_ConfigFormatError_with_bad_yaml_input(self, test_config):
        with pytest.raises(ConfigFormatError):
            test_config(yaml_input="""
            - un
            - deux
            - trois
            """)

    def test_passing_mapping_to_update_adds_keys_as_attrs_with_values(self, test_config):
        """Test the update method adds key value pairs as new class attributes."""
        conf = test_config()
        conf.update({
            'beaches': ['porthcurno', 'sennen'],
            'roads': 'A30',
        })
        assert conf.beaches == ['porthcurno', 'sennen']
        assert conf.roads == 'A30'

    def test_set_attrs_just_updates_if_to_unpack_not_given(self, test_config):
        """Test set_attrs method behaves like update method when to_unpack not given."""
        conf1 = test_config()
        # Loads the same config file as test_config does.
        conf2 = Config('my_config')

        attrs = {'colour': 'green', 'shape': 'circle'}
        conf1.set_attrs(attrs)
        conf2.update(attrs)

        assert vars(conf1) == vars(conf2)

    def test_set_attrs_unpacks_given_mapping_attrs_directly(self, test_config):
        """Test set_attrs method unpacks mappings at attrs given by
        to_unpack directly as attributes.
        """
        conf = test_config()
        attrs = {
            'names': {'jenny': 'female', 'bruce': 'male'},
            'kids': {'terrence': {'age': 12}},
        }
        conf.set_attrs(attrs, to_unpack=['names'])

        attr_keys = vars(conf).keys()
        assert 'jenny' in attr_keys
        assert 'bruce' in attr_keys
        # The mapping at 'names' is also in attribute, in addition to
        # the mapping being unpacked directly.
        assert 'names' in attr_keys
        assert 'kids' in attr_keys

    def test_set_attrs_raises_TypeError_when_attr_to_unpack_is_not_mapping(
        self, test_config
    ):
        """Tests raises TypeError because 'rice' attr is not a mapping"""
        conf = test_config()
        attrs = {'rice': ['uncle_bens', 'tilda'], 'pasta': ['napolina']}
        with pytest.raises(TypeError):
            conf.set_attrs(attrs, to_unpack=['rice'])

    @pytest.mark.parametrize('bad_attr', ['yelp', [1, 2, 3], 5.67])
    def test_set_attrs_raises_ConfigFormatError_when_not_passed_mapping(
        self, test_config, bad_attr
    ):
        """Tests raises ConfigFormatError when using set_attrs."""
        conf = test_config()
        with pytest.raises(ConfigFormatError):
            conf.set_attrs(bad_attr)

    def test_flatten_nested_dicts_only_flattens_given_attrs(self, test_config):
        """Test flatten_nested_dicts flattens the mappings at the given attrs."""
        conf = test_config(yaml_input="""
        bells:
            big_ben:
                dongs: 12
        appearances:
            batman:
                joker: 27
                deadshot: 7
                killer_croc: 12
        """)
        conf.flatten_nested_dicts(['bells'])
        assert conf.bells == {('big_ben', 'dongs') : 12}
        # Check appearances unchanged.
        assert conf.appearances == {'batman': {'joker': 27, 'deadshot': 7, 'killer_croc': 12}}

    def test_get_key_value_pairs_returns_pairs_for_given_attrs(
        self, test_config, all_in_output
    ):
        """Test returns key value pairs for specified attributes."""
        conf = test_config(yaml_input="""
        paris:
            landmarks:
                - arc de triomphe
                - eiffel tower
            museums:
                - le louvre
        london:
            landmarks:
                - big ben
                - st paul's cathedral
        """)
        conf.get_key_value_pairs(['paris'])
        # Use all_in_output as order of a dict is ambiguous.
        assert all_in_output(
            output=conf.paris,
            values=[
                ('landmarks', 'arc de triomphe'),
                ('landmarks', 'eiffel tower'),
                ('museums', 'le louvre'),
            ],
        )
        # Check London unchanged.
        assert conf.london == {'landmarks': ['big ben', 'st paul\'s cathedral']}

    def test_fill_tuples(self, test_config):
        """Test fill_tuples works in place for config attributes."""
        conf = test_config()
        conf.update({'scanner': ['retailer_1', 'retailer_2', 'retailer_3']})
        conf.fill_tuples(['scanner'], repeat=True, length=2)
        assert conf.scanner == [
            ('retailer_1', 'retailer_1'),
            ('retailer_2', 'retailer_2'),
            ('retailer_3', 'retailer_3'),
        ]

    def test_fill_tuple_keys(self, test_config):
        """Test fill_tuple_keys works in place for config attributes."""
        conf = test_config()
        conf.update({
            'food': {
                ('burger', 'patty', 'meat', 'beef'): 4,
                ('burger', 'patty', 'veggie', 'bean'): 3,
                ('burger', 'sauces', 'spicy', 'piri piri'): 1,
                ('hotdog', 'sausage', 'pork',): 3,
                ('chips'): 2
            }
        })
        conf.fill_tuple_keys(['food'], repeat=True)
        assert conf.food == {
            ('burger', 'patty', 'meat', 'beef'): 4,
            ('burger', 'patty', 'veggie', 'bean'): 3,
            ('burger', 'sauces', 'spicy', 'piri piri'): 1,
            ('hotdog', 'hotdog', 'sausage', 'pork',): 3,
            ('chips', 'chips', 'chips', 'chips'): 2
        }

    @parametrize_cases(
        Case(
            "extend_list_with_list",
            attr_val=['jasmine', 'ivy'],
            extend_vals=['bramble', 'lavender'],
            expected=['jasmine', 'ivy', 'bramble', 'lavender'],
        ),
        Case(
            "extend_list_with_tuple",
            attr_val=['jasmine', 'ivy'],
            extend_vals=('bramble', 'lavender'),
            expected=['jasmine', 'ivy', 'bramble', 'lavender'],
        ),
        Case(
            "extend_list_with_single_value_not_sequence",
            attr_val=['jasmine', 'ivy'],
            extend_vals='bramble',
            expected=['jasmine', 'ivy', 'bramble'],
        ),
        Case(
            "extend_tuple_with_tuple",
            attr_val=('jasmine', 'ivy'),
            extend_vals=('bramble',),
            expected=('jasmine', 'ivy', 'bramble'),
        ),
        Case(
            "extend_tuple_with_list",
            attr_val=('jasmine', 'ivy'),
            extend_vals=['bramble'],
            expected=('jasmine', 'ivy', 'bramble'),
        ),
        Case(
            "extend_tuple_with_single_value_not_sequence",
            attr_val=('jasmine', 'ivy'),
            extend_vals='bramble',
            expected=('jasmine', 'ivy', 'bramble'),
        ),
    )
    def test_extend_attr(
        self, test_config,
        attr_val, extend_vals, expected
    ):
        """Test extend_attrs works for tuple and list attrs."""
        conf = test_config()
        conf.update({'plants': attr_val})
        conf.extend_attr('plants', extend_vals)
        assert conf.plants == expected

    @pytest.mark.parametrize(
        'attr_val', [{'rosemary'}, 'rosemary', 5, {'one': 1}],
        ids=lambda x: f"{type(x)}"
    )
    def test_extend_attrs_raises_when_attr_is_wrong_type(
        self, test_config, attr_val,
    ):
        conf = test_config()
        conf.update({'plants': attr_val})
        with pytest.raises(AttributeError):
            conf.extend_attr('plants', ['heather'])

    def test_prepend_dir(self, test_config, make_path_like):
        """Test that the method prepends the given directory to the attrs."""
        conf = test_config()
        conf.update({'mappers': make_path_like('jobs/places.csv')})

        test_dir = 'people'
        conf.prepend_dir(['mappers'], dir=test_dir)
        assert conf.mappers == 'people/jobs/places.csv'

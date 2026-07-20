"""Tests for the source registry (M3: plugin-style registration)."""
import pytest
from datasources.base import (
    BaseDataSource,
    create_source,
    get_source_class,
    list_sources,
    register_source,
    _source_registry,
)
from core.models import SearchQuery, FlightPrice


class TestRegistryBasics:
    def test_registry_is_dict(self):
        assert isinstance(_source_registry, dict)

    def test_list_sources_returns_copy(self):
        sources = list_sources()
        assert isinstance(sources, dict)
        # Should contain at least the core sources
        assert "mock" in sources
        assert "ctrip" in sources
        assert "skyscanner" in sources

    def test_get_source_class_returns_class(self):
        cls = get_source_class("mock")
        assert cls is not None
        assert issubclass(cls, BaseDataSource)

    def test_get_source_class_unknown_returns_none(self):
        assert get_source_class("nonexistent_xyz") is None


class TestCreateSource:
    def test_create_mock_source(self):
        src = create_source("mock")
        assert isinstance(src, BaseDataSource)
        assert src.name == "mock"

    def test_create_ctrip_source(self):
        src = create_source("ctrip")
        assert isinstance(src, BaseDataSource)

    def test_create_unknown_raises(self):
        with pytest.raises(KeyError):
            create_source("nonexistent_xyz")

    def test_create_returns_instance_not_class(self):
        src = create_source("mock")
        assert not isinstance(src, type)


class TestRegisterSource:
    def test_register_new_source(self):
        # Create a temporary source class
        @register_source("test_temp_source")
        class TempSource(BaseDataSource):
            def search_flights(self, query):
                return []

        assert "test_temp_source" in _source_registry
        assert get_source_class("test_temp_source") is TempSource

        # Clean up
        del _source_registry["test_temp_source"]

    def test_register_sets_name_attr(self):
        @register_source("test_named")
        class NamedSource(BaseDataSource):
            def search_flights(self, query):
                return []

        assert NamedSource.name == "test_named"
        del _source_registry["test_named"]


class TestRegisteredSourcesUniformity:
    """Ensure all registered sources follow the BaseDataSource contract."""

    @pytest.fixture(autouse=True)
    def _check_registry(self):
        assert len(list_sources()) >= 3, "Expected at least 3 registered sources"

    def test_all_inherit_base(self):
        for name, cls in list_sources().items():
            assert issubclass(cls, BaseDataSource), f"{name} must inherit BaseDataSource"

    def test_all_have_name_attr(self):
        for name, cls in list_sources().items():
            assert hasattr(cls, 'name'), f"{name} missing class-level name"
            assert len(cls.name) > 0, f"{name} has empty name"

    def test_all_have_search_flights(self):
        for name, cls in list_sources().items():
            assert hasattr(cls, 'search_flights'), f"{name} missing search_flights"

    def test_all_instantiable(self):
        for name in list_sources():
            try:
                src = create_source(name)
                assert src is not None
            except Exception as e:
                pytest.fail(f"Failed to create source '{name}': {e}")

"""
Test Scenario Template Loader

This module loads YAML test scenario templates and converts them into
executable test configurations.
"""

from pathlib import Path
from typing import Dict, Any, List, Optional
import yaml
from pydantic import BaseModel

from backend.models.test_config import (
    TableConfig,
    TableType,
    WarehouseConfig,
    WarehouseSize,
    ScalingPolicy,
    TestScenario,
    WorkloadType,
)


class TemplateMetadata(BaseModel):
    """Metadata about a test template"""

    name: str
    description: str
    version: str
    category: str
    file_path: str


class TemplateLoader:
    """
    Loads and parses YAML test scenario templates.

    Templates are stored in config/test_scenarios/ directory.
    """

    def __init__(self, templates_dir: Optional[Path] = None):
        if templates_dir is None:
            base_dir = Path(__file__).resolve().parent.parent.parent
            templates_dir = base_dir / "config" / "test_scenarios"

        self.templates_dir = Path(templates_dir)
        self._templates_cache: Dict[str, Dict[str, Any]] = {}

    def list_templates(self) -> List[TemplateMetadata]:
        """
        List all available templates.

        Returns:
            List of template metadata
        """
        templates = []

        if not self.templates_dir.exists():
            return templates

        for template_file in self.templates_dir.glob("*.yaml"):
            try:
                with open(template_file, "r") as f:
                    data = yaml.safe_load(f)

                templates.append(
                    TemplateMetadata(
                        name=data.get("name", template_file.stem),
                        description=data.get("description", ""),
                        version=data.get("version", "1.0"),
                        category=data.get("category", "GENERAL"),
                        file_path=str(template_file),
                    )
                )
            except Exception:
                continue

        return templates

    def load_template(self, template_name: str) -> Dict[str, Any]:
        """
        Load a template by name.

        Args:
            template_name: Name of the template file (without .yaml extension)

        Returns:
            Dict with template configuration
        """
        if template_name in self._templates_cache:
            return self._templates_cache[template_name]

        template_file = self.templates_dir / f"{template_name}.yaml"

        if not template_file.exists():
            raise FileNotFoundError(f"Template not found: {template_name}")

        with open(template_file, "r") as f:
            data = yaml.safe_load(f)

        self._templates_cache[template_name] = data
        return data

    def template_to_table_config(self, template_data: Dict[str, Any]) -> TableConfig:
        """
        Convert template table configuration to TableConfig model.

        Args:
            template_data: Template data dictionary

        Returns:
            TableConfig instance
        """
        table_data = template_data.get("table", {})

        table_type = TableType(str(table_data.get("table_type", "STANDARD")).lower())

        config = TableConfig(
            name=table_data.get("name", "test_table"),
            table_type=table_type,
            database=table_data.get("database", "UNISTORE_BENCHMARK"),
            schema_name=table_data.get("schema", "PUBLIC"),
            columns=table_data.get("columns", {}),
        )

        if table_type == TableType.STANDARD or table_type == TableType.INTERACTIVE:
            config.clustering_keys = table_data.get("clustering_keys")
            config.data_retention_days = table_data.get("data_retention_days", 1)

        if table_type == TableType.HYBRID:
            config.primary_key = table_data.get("primary_key")

            indexes = []
            for idx in table_data.get("indexes", []):
                indexes.append(
                    {
                        "name": idx.get("name"),
                        "columns": idx.get("columns", []),
                        "include": idx.get("include_columns", []),
                    }
                )
            config.indexes = indexes if indexes else None

        return config

    def template_to_warehouse_config(
        self, template_data: Dict[str, Any]
    ) -> WarehouseConfig:
        """
        Convert template warehouse configuration to WarehouseConfig model.

        Args:
            template_data: Template data dictionary

        Returns:
            WarehouseConfig instance
        """
        wh_data = template_data.get("warehouse", {})

        size_str = wh_data.get("size", "MEDIUM").upper()
        if size_str == "2XLARGE":
            size = WarehouseSize.XXLARGE
        elif size_str == "3XLARGE":
            size = WarehouseSize.XXXLARGE
        elif size_str == "4XLARGE":
            size = WarehouseSize.X4LARGE
        elif size_str == "5XLARGE":
            size = WarehouseSize.X5LARGE
        elif size_str == "6XLARGE":
            size = WarehouseSize.X6LARGE
        else:
            size = WarehouseSize(size_str)

        config = WarehouseConfig(
            name=wh_data.get("name", "BENCHMARK_WH"),
            size=size,
            auto_suspend_seconds=wh_data.get("auto_suspend", 60),
            auto_resume=wh_data.get("auto_resume", True),
        )

        multi_cluster = wh_data.get("multi_cluster", {})
        if multi_cluster.get("enabled", False):
            config.min_cluster_count = multi_cluster.get("min_clusters", 1)
            config.max_cluster_count = multi_cluster.get("max_clusters", 3)
            config.scaling_policy = ScalingPolicy(
                str(multi_cluster.get("scaling_policy", "STANDARD"))
            )

        return config

    def template_to_test_scenario(self, template_name: str) -> TestScenario:
        """
        Convert a complete template to TestScenario.

        Args:
            template_name: Name of the template file

        Returns:
            TestScenario instance
        """
        data = self.load_template(template_name)

        table_config = self.template_to_table_config(data)

        warehouse_config = self.template_to_warehouse_config(data)

        workload_data = data.get("workload", {})
        workload_type_str = str(workload_data.get("type", "MIXED")).lower()
        try:
            workload_type = WorkloadType(workload_type_str)
        except ValueError:
            workload_type = WorkloadType.MIXED

        test_data = data.get("test", {})

        scenario = TestScenario(
            name=data.get("name", template_name),
            description=data.get("description", ""),
            table_configs=[table_config],
            warehouse_configs=[warehouse_config],
            workload_type=workload_type,
            duration_seconds=test_data.get("duration_seconds", 300),
            concurrent_connections=test_data.get("concurrent_connections", 10),
            warmup_seconds=test_data.get("warmup_seconds", 30),
            think_time_ms=test_data.get("think_time_ms", 0),
        )

        targets = test_data.get("targets", {})
        if targets:
            scenario.target_ops_per_second = targets.get("min_ops_per_second", 100)

        return scenario

    def get_template_summary(self, template_name: str) -> Dict[str, Any]:
        """
        Get a summary of a template without full parsing.

        Args:
            template_name: Name of the template file

        Returns:
            Dict with summary information
        """
        data = self.load_template(template_name)

        table_data = data.get("table", {})
        test_data = data.get("test", {})
        workload_data = data.get("workload", {})

        return {
            "name": data.get("name"),
            "description": data.get("description"),
            "category": data.get("category"),
            "version": data.get("version"),
            "table_type": table_data.get("table_type"),
            "workload_type": workload_data.get("type"),
            "duration_seconds": test_data.get("duration_seconds"),
            "concurrent_connections": test_data.get("concurrent_connections"),
            "targets": test_data.get("targets", {}),
        }


template_loader = TemplateLoader()


def list_available_templates() -> List[TemplateMetadata]:
    """Convenience function to list templates"""
    return template_loader.list_templates()


def load_template_by_name(name: str) -> TestScenario:
    """Convenience function to load template as TestScenario"""
    return template_loader.template_to_test_scenario(name)


def get_template_summary(name: str) -> Dict[str, Any]:
    """Convenience function to get template summary"""
    return template_loader.get_template_summary(name)

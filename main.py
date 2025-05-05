import xml.etree.ElementTree as ET
import json
import os
from typing import Any


class XmlModelParser:
    """Класс для парсинга XML-модели"""
    def __init__(self):
        self.classes: dict[str, dict] = {}
        self.aggregations: list[dict] = []

    def parse(self, xml_path: str) -> dict[str, Any]:
        """Основной метод парсинга"""
        tree = ET.parse(xml_path)
        root = tree.getroot()

        for elem in root:
            if elem.tag == "Class":
                self._process_class_element(elem)
            elif elem.tag == "Aggregation":
                self._process_aggregation_element(elem)

        self._link_aggregations()
        return {"classes": self.classes}

    def _process_class_element(self, elem: ET.Element) -> None:
        """Обработка элемента класса"""
        class_name = elem.attrib["name"]
        self.classes[class_name] = {
            "name": class_name,
            "is_root": elem.attrib["isRoot"] == "true",
            "doc": elem.attrib.get("documentation", ""),
            "attributes": self._parse_attributes(elem),
            "relationships": []
        }

    def _parse_attributes(self, elem: ET.Element) -> list[dict]:
        """Парсинг атрибутов класса"""
        return [
            {"name": attr.attrib["name"], "type": attr.attrib["type"]}
            for attr in elem.findall("Attribute")
        ]

    def _process_aggregation_element(self, elem: ET.Element) -> None:
        """Обработка элемента агрегации"""
        src_mult = elem.attrib["sourceMultiplicity"]
        min_val, max_val = self._parse_multiplicity(src_mult)

        self.aggregations.append({
            "source": elem.attrib["source"],
            "target": elem.attrib["target"],
            "src_min": min_val,
            "src_max": max_val
        })

    @staticmethod
    def _parse_multiplicity(mult: str) -> tuple:
        """Парсинг значения multiplicity"""
        if ".." in mult:
            return mult.strip("[]").split("..")
        return (mult, mult)

    def _link_aggregations(self) -> None:
        """Связывание агрегаций с классами"""
        for agg in self.aggregations:
            target_class = self.classes.get(agg["target"])
            if target_class:
                target_class["relationships"].append({
                    "name": agg["source"],
                    "type": "class",
                    "min": agg["src_min"],
                    "max": agg["src_max"]
                })


class ConfigGenerator:
    """Класс для генерации конфигурационных файлов"""
    def __init__(self, output_dir: str = "out"):
        self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)

    def generate_config_xml(self, model: dict[str, Any]) -> str:
        """Генерация config.xml"""
        def build_xml(class_name: str, indent: int = 0) -> str:
            cls = model["classes"][class_name]
            xml = []
            for attr in cls["attributes"]:
                xml.append(f"{' ' * indent}<{attr['name']}>{attr['type']}</{attr['name']}>")
            for rel in cls["relationships"]:
                xml.append(f"{' ' * indent}<{rel['name']}>")
                xml.append(build_xml(rel["name"], indent + 4))
                xml.append(f"{' ' * indent}</{rel['name']}>")
            return "\n".join(xml)

        root_class = next(cls for cls in model["classes"].values() if cls["is_root"])
        return f"<{root_class['name']}>\n{build_xml(root_class['name'], 4)}\n</{root_class['name']}>"

    def generate_meta_json(self, model: dict[str, Any]) -> list[dict[str, Any]]:
        """Генерация meta.json"""
        meta = []
        for cls in model["classes"].values():
            entry = {
                "class": cls["name"],
                "documentation": cls["doc"],
                "isRoot": cls["is_root"],
                "parameters": [
                    {"name": attr["name"], "type": attr["type"]}
                    for attr in cls["attributes"]
                ]
            }
            for rel in cls["relationships"]:
                entry["parameters"].append({
                    "name": rel["name"],
                    "type": "class"
                })
            meta.append(entry)

        for entry in meta:
            class_name = entry["class"]
            relationships = model["classes"][class_name]["relationships"]
            for rel in relationships:
                related_cls = next((c for c in meta if c["class"] == rel["name"]), None)
                if related_cls:
                    related_cls["min"] = rel["min"]
                    related_cls["max"] = rel["max"]
        return meta

    def save_to_file(self, filename: str, content: Any, is_json: bool = True) -> None:
        """Сохранение в файл"""
        path = os.path.join(self.output_dir, filename)
        with open(path, "w") as f:
            if is_json:
                json.dump(content, f, indent=4)
            else:
                f.write(content)


class ConfigManager:
    """Класс для работы с конфигурациями"""
    @staticmethod
    def compute_delta(original: dict, patched: dict) -> dict:
        """Вычисление дельты между конфигами"""
        delta = {"additions": [], "deletions": [], "updates": []}
        original_keys = set(original.keys())
        patched_keys = set(patched.keys())

        for key in patched_keys - original_keys:
            delta["additions"].append({"key": key, "value": patched[key]})

        delta["deletions"] = list(original_keys - patched_keys)

        for key in original_keys & patched_keys:
            if original[key] != patched[key]:
                delta["updates"].append({
                    "key": key,
                    "from": original[key],
                    "to": patched[key]
                })
        return delta

    @staticmethod
    def apply_delta(config: dict, delta: dict) -> dict:
        """Применение дельты к конфигу"""
        updated = config.copy()
        for key in delta["deletions"]:
            updated.pop(key, None)
        for change in delta["updates"]:
            updated[change["key"]] = change["to"]
        for add in delta["additions"]:
            updated[add["key"]] = add["value"]
        return updated


class Application:
    """Основной класс приложения"""
    def __init__(self):
        self.parser = XmlModelParser()
        self.config_generator = ConfigGenerator()
        self.config_manager = ConfigManager()

    def run(self):
        """Основной метод выполнения программы"""
        model = self.parser.parse("impulse_test_input.xml")

        self.config_generator.save_to_file(
            "config.xml",
            self.config_generator.generate_config_xml(model),
            is_json=False
        )

        self.config_generator.save_to_file(
            "meta.json",
            self.config_generator.generate_meta_json(model)
        )

        with open("config.json") as f:
            original_config = json.load(f)
        with open("patched_config.json") as f:
            patched_config = json.load(f)

        delta = self.config_manager.compute_delta(original_config, patched_config)
        self.config_generator.save_to_file("delta.json", delta)

        result_config = self.config_manager.apply_delta(original_config, delta)
        self.config_generator.save_to_file("res_patched_config.json", result_config)


if __name__ == "__main__":
    app = Application()
    app.run()
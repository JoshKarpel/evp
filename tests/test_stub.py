"""
The type stub against the module it describes,
for what mypy can't check: enum members and missing names.
"""

import ast
import enum
from pathlib import Path

import pytest

import evp
from evp import _evp

STUB = ast.parse(Path(_evp.__file__).with_name("_evp.pyi").read_text())

STUB_ENUMS = {
    node.name: node
    for node in STUB.body
    if isinstance(node, ast.ClassDef)
    and any(isinstance(base, ast.Name) and base.id in {"IntEnum", "IntFlag"} for base in node.bases)
}


def stub_names() -> set[str]:
    names = set()
    for node in STUB.body:
        if isinstance(node, (ast.ClassDef, ast.FunctionDef)):
            names.add(node.name)
        elif isinstance(node, ast.TypeAlias):
            names.add(node.name.id)
    return names


def test_the_stub_names_what_the_module_defines() -> None:
    type_aliases = {"Color", "RGB"}
    module_names = {name for name in dir(_evp) if not name.startswith("_")}
    assert stub_names() - type_aliases == module_names


def test_the_package_exports_what_the_module_defines() -> None:
    assert set(evp.__all__) == {name for name in dir(_evp) if not name.startswith("_")}


@pytest.mark.parametrize("name", sorted(STUB_ENUMS))
def test_a_stub_enum_has_the_modules_members(name: str) -> None:
    stub_members = {
        statement.targets[0].id: ast.literal_eval(statement.value)
        for statement in STUB_ENUMS[name].body
        if isinstance(statement, ast.Assign) and isinstance(statement.targets[0], ast.Name)
    }
    runtime: type[enum.IntEnum] = getattr(_evp, name)
    assert stub_members == {
        member_name: int(member) for member_name, member in runtime.__members__.items()
    }


@pytest.mark.parametrize("name", sorted(STUB_ENUMS))
def test_a_stub_enum_has_the_modules_base(name: str) -> None:
    (base,) = STUB_ENUMS[name].bases
    assert isinstance(base, ast.Name)
    assert getattr(_evp, name).__mro__[1].__name__ == base.id

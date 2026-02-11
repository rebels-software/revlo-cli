# kicad-sch-api Library Specification

**Version**: 0.5.5
**Package**: `kicad_sch_api`
**Purpose**: KiCAD schematic manipulation with exact format preservation, symbol library caching, and AI agent integration via MCP.

---

## 1. Entry Points

```python
import kicad_sch_api as ksa

# Load / create
sch = ksa.load_schematic("circuit.kicad_sch")
sch = ksa.create_schematic("MyProject")

# Grid units mode
ksa.use_grid_units(True)  # positions in grid units instead of mm

# Convert schematic to Python code
ksa.schematic_to_python(input_path, output_path, template, include_hierarchy, format_code, add_comments)
```

---

## 2. Schematic Class

### Construction

```python
# Class methods
Schematic.load(file_path: Union[str, Path]) -> Schematic
Schematic.create(name="Untitled", version=None, generator=None, generator_version=None, paper=None, uuid=None) -> Schematic
```

### Properties

| Property | Type | Description |
|---|---|---|
| `components` | `ComponentCollection` | All components |
| `wires` | `WireCollection` | All wires |
| `junctions` | `JunctionCollection` | All junctions |
| `texts` | `TextCollection` | All text elements |
| `labels` | `LabelCollection` | All labels |
| `hierarchical_labels` | `LabelCollection` | Hierarchical labels |
| `no_connects` | `NoConnectCollection` | No-connect markers |
| `bus_entries` | `BusEntryCollection` | Bus entries |
| `nets` | `NetCollection` | Electrical nets |
| `sheets` | `SheetManager` | Hierarchical sheets |
| `hierarchy` | `HierarchyManager` | Hierarchy operations |
| `library` | `SymbolLibraryCache` | Symbol library cache |
| `version` | `str` | File version |
| `generator` | `str` | Generator name |
| `uuid` | `str` | Schematic UUID |
| `title_block` | `TitleBlock` | Title block metadata |
| `file_path` | `str` | File path |
| `modified` | `bool` | Dirty flag |

### File Operations

```python
sch.save(file_path=None, preserve_format=True)
sch.save_as(file_path, preserve_format=True)
sch.backup(suffix=".backup") -> Path
sch.export_to_python(output_path, template, include_hierarchy, format_code, add_comments) -> Path
```

### Wire Operations

```python
sch.add_wire(start, end, grid_units=None, grid_size=None) -> str  # returns UUID
sch.remove_wire(wire_uuid) -> bool
sch.add_wire_to_pin(start, component_ref, pin_number) -> Optional[str]
sch.add_wire_between_pins(comp1_ref, pin1, comp2_ref, pin2) -> Optional[str]
sch.connect_pins_with_wire(...)  # alias for add_wire_between_pins
sch.auto_route_pins(comp1_ref, pin1, comp2_ref, pin2, routing_strategy) -> List[str]
```

### Label Operations

```python
sch.add_label(text, position=None, pin=None, effects=None, rotation=None, size=None, uuid=None) -> str
sch.add_global_label(...) -> str
sch.add_hierarchical_label(...) -> str
sch.remove_label(label_uuid) -> bool
```

### Text Operations

```python
sch.add_text(text, position, rotation=0, size=None, exclude_from_sim=False, uuid=None) -> str
sch.remove_text(text_uuid) -> bool
```

### Junction / No-Connect Operations

```python
sch.add_junction(position, diameter=0, uuid=None) -> str
sch.remove_junction(junction_uuid) -> bool
sch.add_no_connect(position, uuid=None) -> str
sch.remove_no_connect(nc_uuid) -> bool
```

### Sheet Operations

```python
sch.add_sheet(name, filename, position, size, project_name=None, uuid=None) -> str
sch.add_sheet_pin(sheet_uuid, name, pin_type, edge, position_along_edge, uuid=None) -> str
sch.remove_sheet(sheet_uuid) -> bool
sch.set_hierarchy_context(parent_uuid, sheet_uuid)
```

### Graphics Operations

```python
sch.add_rectangle(start, end, stroke_width=0.127, stroke_type="solid", fill_type="none", stroke_color=None, fill_color=None) -> str
sch.remove_rectangle(rect_uuid) -> bool
sch.add_image(position, scale=1.0, data=None) -> str
sch.draw_bounding_box(bbox, stroke_width=0.127, stroke_color="black") -> str
sch.draw_component_bounding_boxes(include_properties=False) -> List[str]
```

### Metadata

```python
sch.set_title_block(title="", date="", rev="", company="", comments=None)
sch.set_paper_size(paper: str)  # "A4", "A3", etc.
sch.get_paper_sizes() -> List[str]
```

### Connectivity Analysis

```python
sch.get_component_pin_position(reference, pin_number) -> Optional[Point]
sch.list_component_pins(reference) -> List[Tuple[str, Point]]
sch.are_pins_connected(comp1_ref, pin1, comp2_ref, pin2) -> bool
sch.get_net_for_pin(component_ref, pin_number)
sch.get_connected_pins(component_ref, pin_number) -> List[Tuple[str, str]]
```

### Validation & Export

```python
sch.validate() -> List[ValidationIssue]
sch.check_electrical_rules() -> ERCResult
sch.get_netlist(format, include_reference_designators=True) -> str
sch.run_erc(format=None, severity=None) -> Dict[str, Any]
sch.export_netlist(format, filepath=None) -> Optional[str]
sch.export_bom(format="csv", filepath=None, exclude_dnp=True, grouping=None) -> Optional[str]
sch.export_pdf(filepath=None) -> Optional[str]
```

---

## 3. Collections

### ComponentCollection

```python
# Add component — returns Component or MultiUnitComponentGroup
comp = sch.components.add(
    lib_id='Device:R',      # library:symbol
    reference='R1',
    value='10k',
    position=(100, 100),     # tuple or Point
    footprint=None,
    properties=None,         # Dict[str, str]
    unit=1,
    add_all_units=False,     # for multi-unit ICs
    grid_units=None,
    grid_size=None
)

# Lookup
comp = sch.components.get('R1')           # by reference
comps = sch.components.by_lib_id('Device:R')
comps = sch.components.by_footprint('Resistor_SMD:R_0603_1608Metric')
comps = sch.components.filter(lib_id=None, reference_pattern=None)

# Iteration
for comp in sch.components:
    ...
sch.components.count()
sch.components.all()
```

### WireCollection

```python
uuid = sch.wires.add(start=None, end=None, points=None, wire_type=WireType.WIRE, stroke_width=0.0, uuid=None)
wire = sch.wires.get_at_position(position, tolerance=0.01)
wires = sch.wires.filter_by_type(wire_type)
wires = sch.wires.get_wires_touching_position(position)
```

### JunctionCollection

```python
uuid = sch.junctions.add(position, diameter=0, color=(0,0,0,0), uuid=None)
junc = sch.junctions.get_at_position(position, tolerance=0.01)
```

### LabelCollection

```python
uuid = sch.labels.add(text, position, label_type=LabelType.LOCAL, rotation=0, size=1.27, shape=None, uuid=None)
label = sch.labels.get_by_text(text)
label = sch.labels.get_by_position(position, tolerance=0.01)
labels = sch.labels.filter_by_type(label_type)
```

### TextCollection

```python
uuid = sch.texts.add(text, position, rotation=0, size=1.27, exclude_from_sim=False, uuid=None)
```

### Base Collection Methods (inherited by all)

```python
collection.add(...)         # type-specific
collection.remove(uuid)
collection.get(key)
collection.all()
collection.filter(predicate)
collection.map(func)
collection.bulk_add(items)
collection.bulk_remove(uuids)
collection.clear()
collection.count()
collection.first()
collection.last()
collection.exists(predicate)
```

---

## 4. Component Wrapper

```python
comp = sch.components.get('R1')

# Properties
comp.uuid          # str
comp.reference     # str (read/write)
comp.value         # str (read/write)
comp.footprint     # str (read/write)
comp.position      # Point (read/write)
comp.rotation      # float (read/write)
comp.lib_id        # str
comp.library       # str (e.g. "Device")
comp.symbol_name   # str (e.g. "R")
comp.properties    # dict
comp.pins          # list
comp.pin_uuids     # dict (pin_number -> uuid)
comp.in_bom        # bool
comp.on_board      # bool
comp.unit          # int

# Methods
comp.get_property(name, default=None)
comp.set_property(name, value)
comp.remove_property(name) -> bool
comp.add_property(name, value, hidden=False)
comp.add_properties(props: Dict[str, str], hidden=False)
comp.get_pin(pin_number)
comp.get_pin_position(pin_number) -> Point  # accounts for rotation
comp.list_pins() -> List[Dict]
comp.show_pins()  # formatted table
```

### MultiUnitComponentGroup

Returned when `add_all_units=True` for multi-unit components (e.g. op-amps).

```python
group = sch.components.add('Amplifier_Operational:LM358', 'U1', 'LM358', position=(100,100), add_all_units=True)
unit_a = group.get_unit(1)
group.place_unit(2, position=(200, 100))
group.get_all_positions()
group.get_all_references()
```

---

## 5. Geometry Types

### Point

```python
from kicad_sch_api import Point

p = Point(x=100.0, y=50.0)
p.distance_to(other_point)
p.offset(dx, dy) -> Point
```

Frozen dataclass. Helper: `point_from_dict_or_tuple()` converts flexible inputs.

### Rectangle

```python
rect = Rectangle(top_left=Point(0,0), bottom_right=Point(100,50))
rect.width, rect.height, rect.center
rect.contains(point)
```

---

## 6. Electrical Types

### PinType (Enum)

`INPUT`, `OUTPUT`, `BIDIRECTIONAL`, `TRISTATE`, `PASSIVE`, `FREE`, `UNSPECIFIED`, `POWER_IN`, `POWER_OUT`, `OPEN_COLLECTOR`, `OPEN_EMITTER`, `NO_CONNECT`

### PinShape (Enum)

`LINE`, `INVERTED`, `CLOCK`, `INVERTED_CLOCK`, `INPUT_LOW`, `CLOCK_LOW`, `OUTPUT_LOW`, `EDGE_CLOCK_HIGH`, `NON_LOGIC`

### WireType (Enum)

`WIRE`, `BUS`

### LabelType (Enum)

`LOCAL`, `GLOBAL`, `HIERARCHICAL`

### HierarchicalLabelShape (Enum)

`INPUT`, `OUTPUT`, `BIDIRECTIONAL`, `TRISTATE`, `PASSIVE`, `UNSPECIFIED`

---

## 7. Data Models

### SchematicPin

```python
SchematicPin(
    number: str,
    name: str,
    position: Point,
    pin_type: PinType = PinType.PASSIVE,
    pin_shape: PinShape = PinShape.LINE,
    length: float = 2.54,
    rotation: float = 0.0
)
```

### PinInfo

Complete pin information with absolute schematic coordinates.

```python
PinInfo(
    number: str,
    name: str,
    position: Point,           # absolute schematic coords
    electrical_type: PinType,
    shape: PinShape,
    length: float,
    orientation: float,        # degrees
    uuid: str                  # auto-generated if not provided
)
pin_info.to_dict() -> Dict[str, Any]
```

### Wire

```python
Wire(
    uuid: str,
    points: List[Point],       # multi-point support
    wire_type: WireType = WireType.WIRE,
    stroke_width: float = 0.0,
    stroke_type: str = "default"
)
wire.start, wire.end           # first/last points
wire.length
wire.is_simple()               # two points only
wire.is_horizontal(), wire.is_vertical()
Wire.from_start_end(uuid, start, end) -> Wire
```

### Label

```python
Label(
    uuid: str, position: Point, text: str,
    label_type: LabelType = LabelType.LOCAL,
    rotation: float = 0.0, size: float = 1.27,
    shape: Optional[HierarchicalLabelShape] = None,
    justify_h: str = "left", justify_v: str = "top"
)
```

### Text / TextBox

```python
Text(uuid, position, text, rotation=0, size=1.27, exclude_from_sim=False,
     bold=False, italic=False, thickness=None, color=None, face=None)

TextBox(uuid, position, size, text, rotation=0, font_size=1.27, margins=(),
        stroke_width=0, stroke_type="default", fill_type="none",
        justify_horizontal="left", justify_vertical="top", exclude_from_sim=False)
```

### Junction

```python
Junction(uuid: str, position: Point, diameter: float = 0, color: Tuple[int,int,int,int] = (0,0,0,0))
```

### BusEntry

```python
BusEntry(uuid, position, size=Point(2.54, 2.54), rotation=0, stroke_width=0.0, stroke_type="default")
```

### Net

```python
Net(name: str, components: List[Tuple[str, str]], wires: List[str], labels: List[str])
net.add_connection(reference, pin)
net.remove_connection(reference, pin)
```

### Sheet / SheetPin

```python
Sheet(uuid, position, size, name, filename, pins: List[SheetPin],
      exclude_from_sim=False, in_bom=True, on_board=True, dnp=False)

SheetPin(uuid, name, position, pin_type: PinType, size: float)
```

### TitleBlock

```python
TitleBlock(title="", company="", rev="", date="", size="A4", comments: Dict[int, str] = {})
```

### SymbolInstance

```python
SymbolInstance(path: str, reference: str, unit: int, project: str)
```

---

## 8. Symbol Library

### SymbolLibraryCache

```python
cache = ksa.SymbolLibraryCache()
# or access via schematic
cache = sch.library

sym = cache.get_symbol('Device:R') -> Optional[SymbolDefinition]
results = cache.search_symbols('capacitor') -> List[SymbolDefinition]
cache.get_library_path('Device') -> Optional[Path]
cache.add_library_path('/path/to/library')
cache.preload_library('Device')
cache.clear_cache()
cache.get_cache_stats()
```

### SymbolDefinition

```python
SymbolDefinition(
    lib_id: str,              # e.g. "Device:R"
    name: str,                # e.g. "R"
    library: str,             # e.g. "Device"
    reference_prefix: str,    # e.g. "R"
    description: str,
    keywords: str,
    datasheet: str,
    pins: List[SchematicPin],
    units: int,
    unit_names: Dict[int, str],
    power_symbol: bool,
    graphic_elements: List[Dict],
    property_positions: Dict[str, Tuple[float, float, float]],
    raw_kicad_data: Any,
    extends: Optional[str]    # symbol inheritance
)

sym.bounding_box              # computed property
sym.size                      # computed property
sym.get_pin(pin_number) -> Optional[SchematicPin]
sym.get_pins_by_type(pin_type) -> List[SchematicPin]
sym.list_pins() -> List[Dict]
```

### Module-Level Functions

```python
from kicad_sch_api.library.cache import get_symbol_cache, get_symbol_info, search_symbols

cache = get_symbol_cache()
info = get_symbol_info('Device:R') -> Optional[SymbolInfo]
results = search_symbols('opamp', max_results=50) -> List[SymbolDefinition]
```

---

## 9. Validation

### Schematic Validation

```python
issues = sch.validate() -> List[ValidationIssue]
```

### ValidationIssue

```python
ValidationIssue(
    category: str,       # "syntax", "reference", "connection"
    message: str,
    level: ValidationLevel,  # INFO, WARNING, ERROR, CRITICAL
    context: Optional[Dict],
    suggestion: Optional[str]
)
```

### Electrical Rules Check (ERC)

```python
from kicad_sch_api.validation import ElectricalRulesChecker

erc = ElectricalRulesChecker(sch, config=None)
erc.add_validator(validator)
result = erc.run_all_checks() -> ERCResult
violations = erc.run_check('pin_type') -> List[ERCViolation]
```

### ERCResult

```python
result.errors       # List[ERCViolation]
result.warnings     # List[ERCViolation]
result.info         # List[ERCViolation]
result.total_checks
result.passed_checks
result.duration_ms
result.has_errors() -> bool
result.summary() -> str
result.to_json() -> str
```

### ERCViolation

```python
ERCViolation(
    violation_type: str,
    severity: str,           # "error", "warning", "info"
    message: str,
    component_refs: List[str],
    error_code: str,
    net_name: Optional[str],
    pin_numbers: List[str],
    location: Optional[Point],
    suggested_fix: Optional[str]
)
```

### Built-in Validators

- `PinTypeValidator` — pin type conflict detection
- `ConnectivityValidator` — open nets, dangling wires
- `ComponentValidator` — component property checks
- `PowerValidator` — power connection validation

---

## 10. Connectivity Analysis

```python
from kicad_sch_api.core.connectivity import ConnectivityAnalyzer, PinConnection

analyzer = ConnectivityAnalyzer(tolerance=0.01)
nets = analyzer.analyze(schematic, hierarchical=True) -> List[Net]
pins = analyzer.find_connected_pins(pin_position) -> List[PinConnection]
net = analyzer.trace_net(start_point, name=None) -> Net
```

### PinConnection

```python
PinConnection(reference: str, pin_number: str, position: Point)
```

---

## 11. BOM

```python
from kicad_sch_api.bom import BOMPropertyAuditor

auditor = BOMPropertyAuditor()
issues = auditor.audit_schematic(schematic_path, required_properties=['MPN', 'Manufacturer'], exclude_dnp=False)
issues = auditor.audit_directory(directory, required_properties, recursive=True)
auditor.generate_csv_report(issues, output_path)
auditor.bulk_update_properties(...)
```

---

## 12. CLI Wrappers

```python
from kicad_sch_api.cli import KiCadExecutor, set_execution_mode, ExecutionMode

set_execution_mode(ExecutionMode.LOCAL)  # or DOCKER, AUTO

executor = KiCadExecutor(schematic_path)
executor.run_erc(format=None, severity=None) -> Dict
executor.export_netlist(format, output_path=None) -> str
executor.export_bom(format, output_path=None, exclude_dnp=True) -> str
executor.export_pdf(output_path=None) -> str
executor.export_svg(output_path=None) -> str
executor.export_dxf(output_path=None) -> str
```

### Netlist Formats

`KICAD`, `PSPICE`, `TINYSPICE`, `NGSPICE`, `CADENCE`, `ALLEGRO`, `PADS`, `ORCAD`

---

## 13. Code Generation

```python
from kicad_sch_api.exporters import PythonCodeGenerator

gen = PythonCodeGenerator(template="default", format_code=True, add_comments=True)
# Templates: "minimal", "default", "verbose", "documented"
gen.generate(schematic, include_hierarchy=False, output_path="output.py") -> Path
```

---

## 14. Configuration

```python
from kicad_sch_api.core.config import config  # global KiCADConfig instance

# Grid settings
config.grid.standard_grid       # 1.27mm (50mil)
config.grid.component_spacing   # 2.54mm (100mil)

# Positioning
config.positioning.use_grid_units  # bool
config.positioning.grid_size       # float (mm)

# Tolerances
config.tolerance.position_tolerance
config.tolerance.coordinate_precision

# Defaults
config.defaults.project_name
config.defaults.stroke_width
config.defaults.font_size
```

---

## 15. Geometry Utilities

```python
from kicad_sch_api.core.geometry import (
    snap_to_grid,
    points_equal,
    distance_between_points,
    apply_transformation,
    calculate_bounding_box
)

snap_to_grid(position, grid_size=2.54) -> Tuple[float, float]
points_equal(p1, p2, tolerance=0.01) -> bool
distance_between_points(p1, p2) -> float
apply_transformation(point, origin, rotation, mirror=None) -> Tuple[float, float]
calculate_bounding_box(elements) -> Tuple[float, float, float, float]
```

---

## 16. Exceptions

All inherit from `KiCadSchError`.

| Exception | Description |
|---|---|
| `ValidationError` | Validation failure (has `.issues`, `.get_errors()`, `.get_warnings()`) |
| `ReferenceError` | Invalid component reference |
| `LibraryError` | Invalid library/symbol reference |
| `GeometryError` | Geometry validation failure |
| `NetError` | Invalid net specification |
| `ParseError` | File parsing failure |
| `FormatError` | File formatting failure |
| `CollectionError` | Collection operation failure |
| `ElementNotFoundError` | Element not found in collection |
| `DuplicateElementError` | Duplicate element in collection |
| `CollectionOperationError` | Collection operation failure |
| `FileOperationError` | File I/O failure |
| `CLIError` | KiCad CLI execution failure |
| `SchematicStateError` | Schematic requires specific state |

---

## 17. Typical Workflows

### Create a simple circuit

```python
import kicad_sch_api as ksa

sch = ksa.create_schematic("Voltage Divider")
sch.set_title_block(title="Voltage Divider", rev="1.0")

r1 = sch.components.add('Device:R', 'R1', '10k', position=(100, 80))
r2 = sch.components.add('Device:R', 'R2', '10k', position=(100, 110))

sch.connect_pins_with_wire('R1', '2', 'R2', '1')
sch.add_label('VDIV', pin=('R1', '2'))

sch.save('voltage_divider.kicad_sch')
```

### Analyze an existing schematic

```python
sch = ksa.load_schematic('circuit.kicad_sch')

for comp in sch.components:
    print(f"{comp.reference}: {comp.value} ({comp.lib_id})")
    for pin in comp.list_pins():
        print(f"  Pin {pin['number']}: {pin['name']}")

connected = sch.are_pins_connected('U1', '1', 'R1', '2')
issues = sch.validate()
erc_result = sch.check_electrical_rules()
print(erc_result.summary())
```

### Export

```python
sch.export_bom(format="csv", filepath="bom.csv")
sch.export_netlist(format="kicad", filepath="netlist.net")
sch.export_pdf(filepath="schematic.pdf")
sch.export_to_python("recreate_circuit.py", template="documented")
```

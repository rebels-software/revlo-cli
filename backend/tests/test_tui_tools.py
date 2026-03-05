"""Tests for Ask Mode investigation tools."""

from __future__ import annotations

from revlo.parser.models import (
    ParsedComponent,
    ParsedNet,
    ParsedPin,
    ParsedSchematic,
    PinConnection,
)
from revlo.tui.tools import execute_tool


def _make_investigation_schematic() -> ParsedSchematic:
    return ParsedSchematic(
        components=[
            ParsedComponent(
                reference="U1",
                value="STM32F103C8T6",
                lib_id="MCU_ST:STM32F103C8T6",
                footprint="LQFP-48",
                source_sheet="/MCU",
                pins=[
                    ParsedPin(number="1", name="VDD", electrical_type="power_in", connected_net="+3V3"),
                    ParsedPin(number="2", name="NRST", electrical_type="input", connected_net="NRST"),
                    ParsedPin(number="3", name="BOOT0", electrical_type="input", connected_net="BOOT0"),
                    ParsedPin(number="4", name="USB_DM", electrical_type="bidirectional", connected_net="USB_D-"),
                    ParsedPin(number="5", name="USB_DP", electrical_type="bidirectional", connected_net="USB_D+"),
                    ParsedPin(number="6", name="USART_TX", electrical_type="output", connected_net="UART_TX"),
                    ParsedPin(number="7", name="USART_RX", electrical_type="input", connected_net="UART_RX"),
                    ParsedPin(number="8", name="VSS", electrical_type="power_in", connected_net="GND"),
                ],
            ),
            ParsedComponent(
                reference="U2",
                value="AMS1117-3.3",
                lib_id="Regulator_Linear:AMS1117-3.3",
                footprint="SOT-223",
                source_sheet="/Power",
                pins=[
                    ParsedPin(number="1", name="GND", electrical_type="power_in", connected_net="GND"),
                    ParsedPin(number="2", name="VOUT", electrical_type="power_out", connected_net="+3V3"),
                    ParsedPin(number="3", name="VIN", electrical_type="power_in", connected_net="+5V"),
                ],
            ),
            ParsedComponent(
                reference="C1",
                value="100nF",
                lib_id="Device:C",
                footprint="0402",
                source_sheet="/MCU",
                pins=[
                    ParsedPin(number="1", name="1", electrical_type="passive", connected_net="+3V3"),
                    ParsedPin(number="2", name="2", electrical_type="passive", connected_net="GND"),
                ],
            ),
            ParsedComponent(
                reference="C2",
                value="1uF",
                lib_id="Device:C",
                footprint="0603",
                source_sheet="/Power",
                pins=[
                    ParsedPin(number="1", name="1", electrical_type="passive", connected_net="+3V3"),
                    ParsedPin(number="2", name="2", electrical_type="passive", connected_net="GND"),
                ],
            ),
            ParsedComponent(
                reference="R1",
                value="10k",
                lib_id="Device:R",
                footprint="0402",
                source_sheet="/MCU",
                pins=[
                    ParsedPin(number="1", name="1", electrical_type="passive", connected_net="NRST"),
                    ParsedPin(number="2", name="2", electrical_type="passive", connected_net="+3V3"),
                ],
            ),
            ParsedComponent(
                reference="SW1",
                value="RESET",
                lib_id="Switch:SW_Push",
                footprint="SW_Push",
                source_sheet="/MCU",
                pins=[
                    ParsedPin(number="1", name="1", electrical_type="passive", connected_net="NRST"),
                    ParsedPin(number="2", name="2", electrical_type="passive", connected_net="GND"),
                ],
            ),
            ParsedComponent(
                reference="R2",
                value="100k",
                lib_id="Device:R",
                footprint="0402",
                source_sheet="/MCU",
                pins=[
                    ParsedPin(number="1", name="1", electrical_type="passive", connected_net="BOOT0"),
                    ParsedPin(number="2", name="2", electrical_type="passive", connected_net="GND"),
                ],
            ),
            ParsedComponent(
                reference="J1",
                value="USB_C",
                lib_id="Connector:USB_C_Receptacle",
                footprint="USB_C",
                source_sheet="/IO",
                pins=[
                    ParsedPin(number="1", name="VBUS", electrical_type="power_in", connected_net="+5V"),
                    ParsedPin(number="2", name="D-", electrical_type="bidirectional", connected_net="USB_D-"),
                    ParsedPin(number="3", name="D+", electrical_type="bidirectional", connected_net="USB_D+"),
                    ParsedPin(number="4", name="GND", electrical_type="power_in", connected_net="GND"),
                ],
            ),
            ParsedComponent(
                reference="U3",
                value="CH340G",
                lib_id="Interface_USB:CH340G",
                footprint="SOIC-16",
                source_sheet="/IO",
                pins=[
                    ParsedPin(number="1", name="TXD", electrical_type="output", connected_net="UART_RX"),
                    ParsedPin(number="2", name="RXD", electrical_type="input", connected_net="UART_TX"),
                ],
            ),
        ],
        nets=[
            ParsedNet(
                name="+3V3",
                is_power=True,
                pins=[
                    PinConnection(component_ref="U1", pin_number="1", pin_name="VDD"),
                    PinConnection(component_ref="U2", pin_number="2", pin_name="VOUT"),
                    PinConnection(component_ref="C1", pin_number="1", pin_name="1"),
                    PinConnection(component_ref="C2", pin_number="1", pin_name="1"),
                    PinConnection(component_ref="R1", pin_number="2", pin_name="2"),
                ],
            ),
            ParsedNet(
                name="+5V",
                is_power=True,
                pins=[
                    PinConnection(component_ref="U2", pin_number="3", pin_name="VIN"),
                    PinConnection(component_ref="J1", pin_number="1", pin_name="VBUS"),
                ],
            ),
            ParsedNet(
                name="GND",
                is_power=True,
                pins=[
                    PinConnection(component_ref="U1", pin_number="8", pin_name="VSS"),
                    PinConnection(component_ref="U2", pin_number="1", pin_name="GND"),
                    PinConnection(component_ref="C1", pin_number="2", pin_name="2"),
                    PinConnection(component_ref="C2", pin_number="2", pin_name="2"),
                    PinConnection(component_ref="SW1", pin_number="2", pin_name="2"),
                    PinConnection(component_ref="R2", pin_number="2", pin_name="2"),
                    PinConnection(component_ref="J1", pin_number="4", pin_name="GND"),
                ],
            ),
            ParsedNet(
                name="NRST",
                pins=[
                    PinConnection(component_ref="U1", pin_number="2", pin_name="NRST"),
                    PinConnection(component_ref="R1", pin_number="1", pin_name="1"),
                    PinConnection(component_ref="SW1", pin_number="1", pin_name="1"),
                ],
            ),
            ParsedNet(
                name="BOOT0",
                pins=[
                    PinConnection(component_ref="U1", pin_number="3", pin_name="BOOT0"),
                    PinConnection(component_ref="R2", pin_number="1", pin_name="1"),
                ],
            ),
            ParsedNet(
                name="USB_D-",
                labels=["USB_D-"],
                pins=[
                    PinConnection(component_ref="U1", pin_number="4", pin_name="USB_DM"),
                    PinConnection(component_ref="J1", pin_number="2", pin_name="D-"),
                ],
            ),
            ParsedNet(
                name="USB_D+",
                labels=["USB_D+"],
                pins=[
                    PinConnection(component_ref="U1", pin_number="5", pin_name="USB_DP"),
                    PinConnection(component_ref="J1", pin_number="3", pin_name="D+"),
                ],
            ),
            ParsedNet(
                name="UART_TX",
                pins=[
                    PinConnection(component_ref="U1", pin_number="6", pin_name="USART_TX"),
                    PinConnection(component_ref="U3", pin_number="2", pin_name="RXD"),
                ],
            ),
            ParsedNet(
                name="UART_RX",
                pins=[
                    PinConnection(component_ref="U1", pin_number="7", pin_name="USART_RX"),
                    PinConnection(component_ref="U3", pin_number="1", pin_name="TXD"),
                ],
            ),
        ],
    )


def test_find_decoupling_caps_reports_caps_on_power_net():
    result = execute_tool(
        "find_decoupling_caps",
        {"ref": "U1"},
        _make_investigation_schematic(),
    )

    assert "Likely decoupling capacitors for U1" in result
    assert "+3V3" in result
    assert "C1 (100nF)" in result
    assert "C2 (1uF)" in result


def test_trace_power_tree_shows_observed_connections_and_source_inference():
    result = execute_tool(
        "trace_power_tree",
        {"net_name": "+3V3"},
        _make_investigation_schematic(),
    )

    assert "Power trace for +3V3" in result
    assert "Observed connections: C1, C2, R1, U1, U2" in result
    assert "Likely source components: U2 (observed upstream nets: +5V, GND)" in result
    assert "Inference note" in result


def test_find_reset_chain_finds_reset_net_and_pulls():
    result = execute_tool(
        "find_reset_chain",
        {"ref": "U1"},
        _make_investigation_schematic(),
    )

    assert "Reset chain investigation" in result
    assert "Net NRST" in result
    assert "Observed refs: R1, SW1, U1" in result
    assert "Pull network: R1 -> +3V3" in result
    assert "Control path: SW1 -> GND" in result

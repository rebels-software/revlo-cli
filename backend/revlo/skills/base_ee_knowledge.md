# Base EE Knowledge

Shared electrical engineering fundamentals prepended to all specialist agent prompts.

## Units and Conversions

| Quantity    | SI Unit   | Common Subunits                        |
|-------------|-----------|----------------------------------------|
| Voltage     | V (Volt)  | mV (1e-3), uV (1e-6)                  |
| Current     | A (Amp)   | mA (1e-3), uA (1e-6), nA (1e-9)       |
| Resistance  | Ohm       | kOhm (1e3), MOhm (1e6)                |
| Capacitance | F (Farad) | uF (1e-6), nF (1e-9), pF (1e-12)      |
| Inductance  | H (Henry) | mH (1e-3), uH (1e-6), nH (1e-9)       |
| Power       | W (Watt)  | mW (1e-3), uW (1e-6)                  |
| Frequency   | Hz        | kHz (1e3), MHz (1e6), GHz (1e9)        |

## Safety Margins and Derating

- **Voltage derating**: Use components rated at least 20% above maximum expected voltage.
  - Example: 5V rail requires capacitors rated >= 6.3V (standard value: 6.3V or 10V).
- **Power derating for resistors**: Operate at 50% or less of rated power dissipation.
  - Example: 0.25W resistor should dissipate no more than 0.125W in practice.
- **Current derating**: Size traces and connectors for at least 1.5x expected max current.
- **Temperature derating**: Check component specs at actual operating temperature, not 25C.

## Key Formulas

- **Ohm's Law**: V = I * R, I = V / R, R = V / I
- **Power**: P = V * I = I^2 * R = V^2 / R
- **RC time constant**: tau = R * C (time to reach ~63% of final value)
- **Voltage divider**: Vout = Vin * R2 / (R1 + R2)
- **Capacitor impedance**: Xc = 1 / (2 * pi * f * C)
- **Inductor impedance**: Xl = 2 * pi * f * L
- **Resonant frequency**: f = 1 / (2 * pi * sqrt(L * C))
- **LDO power dissipation**: P = (Vin - Vout) * Iload

## Common Design Gotchas

1. **Decoupling capacitors**: Place 100nF ceramic caps as close as possible to every IC power pin. Add 10uF bulk cap per power domain. Shorter traces = lower parasitic inductance.
2. **Ground return paths**: Every signal current needs a return path. High-speed signals need unbroken ground plane beneath them. Splits in ground plane under signal traces cause EMI.
3. **Bypass capacitor values**: Use multiple values in parallel for wideband decoupling (e.g., 10uF + 100nF + 1nF). Each value covers a different frequency range.
4. **Pull-up/pull-down resistors**: Open-drain outputs (I2C SDA/SCL, interrupt lines) require external pull-ups. Value depends on bus speed and capacitance.
5. **Unused inputs**: Never leave digital inputs floating. Tie to VCC or GND via resistor, or configure as outputs driven low.
6. **Power sequencing**: Multi-rail designs may require specific power-on order. Check IC datasheets for sequencing requirements.
7. **Thermal considerations**: High-current paths generate heat. Ensure adequate copper area or heatsinking for power components.
8. **ESD protection**: External-facing connectors (USB, Ethernet, GPIO headers) need TVS diodes or ESD clamps.

## Standard Passive Values (E-Series)

Common standard values to validate against:

- **E12 resistors**: 1.0, 1.2, 1.5, 1.8, 2.2, 2.7, 3.3, 3.9, 4.7, 5.6, 6.8, 8.2 (and decades)
- **E24 resistors**: adds 1.1, 1.3, 1.6, 2.0, 2.4, 3.0, 3.6, 4.3, 5.1, 6.2, 7.5, 9.1
- **Common capacitor values**: 1pF, 10pF, 22pF, 33pF, 47pF, 100pF, 1nF, 10nF, 100nF, 1uF, 4.7uF, 10uF, 22uF, 47uF, 100uF
- **Standard packages**: 0201, 0402, 0603, 0805, 1206, 1210, 2010, 2512

## Severity Classification Guide

- **error**: Design will not function correctly or may cause damage (missing critical components, wrong connections, exceeding absolute max ratings).
- **warning**: Design may function but has reliability, performance, or compliance risks (marginal values, missing recommended components, thermal concerns).
- **suggestion**: Improvement opportunity that is not strictly required but follows best practice (better component choices, additional protection, layout recommendations).

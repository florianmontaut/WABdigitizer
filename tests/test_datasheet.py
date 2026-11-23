"""Sens des datasheets (model/datasheet.py) : extraits de texte de plusieurs fabricants."""
import numpy as np

from model import datasheet as ds


def test_identite_premiere_page():
    infineon = ds.identify([("IMT40R045M2H", 14), ("Final datasheet", 14),
                            ("400V CoolSiC™ G2 MOSFET", 12), ("www.infineon.com", 9),
                            ("Commutation robust fast body diode", 9)],
                           "infineon-imt40r045m2h-datasheet-en.pdf")
    assert (infineon.part_number, infineon.manufacturer, infineon.category) == \
        ("IMT40R045M2H", "Infineon", "MOSFET")
    assert infineon.description == "400V CoolSiC™ G2 MOSFET"
    st = ds.identify([("SCT011HU75G3AG", 16), ("Automotive-grade silicon carbide Power MOSFET "
                                              "750 V, 11.4 mΩ typ., 110 A", 14),
                      ("© 2024 STMicroelectronics – All rights reserved", 8)], "DS_sct.pdf")
    assert (st.part_number, st.manufacturer, st.category) == \
        ("SCT011HU75G3AG", "STMicroelectronics", "MOSFET")
    # fabricant en logo seulement : nom du fichier ; « increase » ne donne pas « cree »
    module = ds.identify([("FF300R12KT4", 22), ("IGBT-modules", 10), ("I_C increase", 8),
                          ("Diode, Wechselrichter", 8)], "infineon-ff300r12kt4-datasheet-en.pdf")
    assert (module.part_number, module.manufacturer, module.category) == \
        ("FF300R12KT4", "Infineon", "IGBT")
    jfet = ds.identify([("Silicon Carbide (SiC) JFET –", 18), ("UF3N120007K4S", 18),
                        ("www.onsemi.com", 8)], "UF3N120007K4S-D.PDF")
    assert (jfet.part_number, jfet.manufacturer, jfet.category) == ("UF3N120007K4S", "onsemi", "JFET")
    assert ds.identify([], "x.pdf") == ds.Identity()


def test_axes_symboles_unites():
    assert ds.axis("I_D, Drain Current", "A") == ("I_D", "A", "Drain Current")
    assert ds.axis("Drain Current : I_D", "A") == ("I_D", "A", "Drain Current")
    assert ds.axis("R_DS(on)", "mohm")[:2] == ("R_DS(on)", "mΩ")
    assert ds.axis("T_vj", "ºC")[:2] == ("T_vj", "°C")
    assert ds.axis("R_DS(on), On-Resistance", "P.U.") == ("R_DS(on)", "", "normalisée, On-Resistance")
    assert ds.dimension("pF") == "capacité" and ds.dimension("mJ") == "énergie"
    assert ds.dimension("") == "" and ds.dimension("P.U.") == ""


def test_lettres_perdues_et_caracteres():
    known = ("V_DS", "I_D")
    assert ds.fix_symbols("_D=f( _DS), _j=25 °C; parameter: _GS", known) == \
        "I_D=f( V_DS), T_j=25 °C; parameter: _GS"
    assert ds.fix_symbols("_DD=200 V, _D=8.9 A", ()) == "V_DD=200 V, I_D=8.9 A"
    assert ds.clean("T_J = 25 ¤C, t_p < 250 ¤s") == "T_J = 25 °C, t_p < 250 µs"
    assert ds.clean("Tvj = 150^oC") == "Tvj = 150°C" and ds.clean("0.23 ℃/W") == "0.23 °C/W"


def test_parametre_et_plages():
    assert ds.parameter("I_D=f(V_DS), T_j=25 °C; parameter: V_GS") == "V_GS"
    assert ds.parameter("Diagram 1: Power dissipation") is None
    assert ds.curve_condition("8 V", "V_GS") == "V_GS = 8 V"
    assert ds.curve_condition("Tj = 25 °C", "V_GS") == "Tj = 25 °C"
    assert ds.curve_condition("Ciss", "V_GS") == "Ciss"
    assert ds.expand_range("V_GS = 6~18V, 2V step") == ("V_GS", [6, 8, 10, 12, 14, 16, 18], "V")
    assert ds.expand_range("VGS= 12, 14, 16, 18 V") == ("VGS", [12, 14, 16, 18], "V")
    assert ds.expand_range("RthJC = 0.23 °C/W") is None
    assert ds.expand_range("V_GS = 6~18V, 5V step") is None          # 18 pas atteint
    # rangées par amplitude de courant croissante
    assert ds.assign_range([30.0, 5.0, 80.0], [6, 12, 18]) == [12, 6, 18]
    assert ds.assign_range([1.0], [6, 12]) is None
    assert ds.format_value(-4.0, "V") == "−4 V"


def test_caracteristiques_et_roles():
    c = ds.classify
    assert c("V_DS", "V", "I_D", "A", "Diagram 5: Typ. output characteristics") == "output"
    assert c("V_GS", "V", "I_D", "A", "Typical transfer characteristics") == "transfer"
    assert c("V_SD", "V", "I_S", "A", "Reverse output characteristics") == "diode"
    assert c("V_DS", "V", "I_D", "A", "Fig.5 3rd Quadrant Characteristics") == "diode"
    assert c("I_C", "A", "V_CE", "V", "") == "conduction"
    assert c("I_C", "A", "E", "mJ", "Switching losses") == "energy"
    assert c("R_G", "Ω", "E_on", "µJ", "") == "energy_other"
    assert c("t_p", "s", "Z_thJC", "K/W", "") == "zth"
    assert c("V_DS", "V", "C", "pF", "") == "capacitance"
    assert c("V_DS", "V", "I_D", "A", "Figure 1. Safe operating area") == "soa"
    assert c("V_CE", "V", "I_C", "A", "Reverse bias safe operating area (RBSOA)") == "soa"
    assert c("T_j", "°C", "V_GS(th)", "V", "") == "other"
    assert ds.energy_kind("E_on, T_vj = 125°C") == "on" and ds.energy_kind("Erec") == "rec"
    assert ds.energy_kind("Ciss") is None
    assert ds.diode_graph("Durchlasskennlinie der Diode, Wechselrichter", "V_F", "I_F")
    assert not ds.diode_graph("output characteristic IGBT, Inverter", "V_CE", "I_C")
    assert ds.diode_graph("Schaltverluste", "R_G", "E", ["E_rec, T_vj = 125°C"])
    role = ds.plecs_role
    assert role("output", [25.0, 150.0]) == "conduction"
    assert role("output", [25.0, 25.0]) == ""          # réseau selon VGS : pas une table PLECS
    assert role("output", [25.0, None]) == ""
    assert role("energy", [150.0], "on") == "turn_on" and role("energy", [150.0], "off") == "turn_off"
    assert role("energy", [125.0], "rec") == "" and role("energy", [125.0], "rec", True) == "turn_off"
    assert role("diode", [25.0, 150.0]) == "" and role("diode", [25.0, 150.0], diode_part=True) == "conduction"
    assert role("zth", [None]) == ""


def test_conduction_plecs_sur_sortie_et_jfet():
    """Export PLECS : i(v) échangée, 3e quadrant en valeurs absolues ; JFET comme MOSFET."""
    from model import document, plecs
    from model.calibration import AxisCalibration
    c = document.Component(part_number="J1", category="JFET")
    graph = c.add_graph(np.full((10, 10, 3), 255, np.uint8), "sortie")
    graph.set_calibration(AxisCalibration((0, 100), (100, 100), (0, 100), (0, 0), 0, 4, 0, 400))
    graph.x_axis, graph.y_axis = document.Axis("VDS", "V"), document.Axis("ID", "A")
    graph.plecs_role = "conduction"
    graph.datasets[0].set_data([(0.5, 50), (1.0, 100), (2.0, 200)], graph.calibration)
    graph.datasets[0].temperature = 25.0
    third = graph.add_dataset("3e quadrant")
    third.set_data([(-2.0, -200), (-1.0, -100)], graph.calibration)
    third.temperature = 150.0
    curves = plecs.collect(c, "conduction")
    assert np.allclose(curves[0]["i"], [50, 100, 200]) and np.allclose(curves[0]["y"], [0.5, 1, 2])
    assert np.allclose(curves[1]["i"], [100, 200]) and np.allclose(curves[1]["y"], [1, 2])
    _, warnings = plecs.build(c)
    assert any("JFET" in w for w in warnings)


def test_axes_d_apres_la_legende():
    """Graphique en image : axes lus dans « Y = f(X) », grandeur d'après la lettre."""
    assert ds.function_axes("(I_SD = f(V_SD), T_vj = 25°C, t_P = 20µs)") == ("ISD", "VSD")
    assert ds.function_axes("Figure 10 Typical gate charge (V_GS = f(Q_G), I_DS = 20A,") \
        == ("VGS", "QG")
    assert ds.function_axes("Typical switching energy losses") is None
    assert ds.classify("IDS", "A", "E", "", "switching energy losses") == "energy"
    assert ds.classify("Tvj", "°C", "E", "", "switching energy losses") == "energy_other"
    assert ds.classify("VSD", "V", "ISD", "A", "body diode forward current") == "diode"
    assert ds.expand_range("R_G,ext = 2, 5, 10 Ω")[0] == "R_G,ext"

# model/signals.py
"""
Calculs entre signaux (voies calculées, « MATH » d'un oscilloscope) : formules sur les
courbes d'un composant, évaluées avec le moteur de formules partagé (paquet formules,
celui du GLviewer et de loggerFPGA).

    P   = [Vce]*[Ic]                    puissance instantanée (unité déduite : W)
    E   = integ([Vce]*[Ic]; 0; 2e-6)    énergie entre deux instants (nombre, J)
    dV  = deriv([Vce])                  dérivée (V/s)
    Vm  = movavg([Vce]; 15)             moyenne glissante sur 15 points

Désignation des signaux (courbes d'un graphique calibré, en unités physiques) :
    [Vce]          graphique d'une seule courbe, par son nom (ou courbe de nom unique)
    [Graphique:Courbe]   une courbe d'un graphique
    [P]            voie calculée définie plus haut dans la liste
    time, t        temps (abscisse, s)
Fonctions de formules : sin cos tan exp log log10 sqrt abs, max min sum avg, tables
interp / steps. Ajoutées (abscisses irrégulières, temps réel des points) :
    deriv(x)                  dérivée
    integ(x)                  intégrale cumulée depuis le début
    integ(x; t1; t2)          intégrale entre deux instants (nombre)
    mean(x), mean(x; t1; t2)  moyenne pondérée par le temps (nombre)
    rms(x), rms(x; t1; t2)    valeur efficace (nombre)
    pkpk(x), pkpk(x; t1; t2)  crête-crête (nombre)
    movavg(x; n)              moyenne glissante centrée sur n points

Signaux non synchrones (GLviewer, model/computed.py) : les signaux utilisés sont
interpolés sur une base de temps, la plus fine d'entre eux sur leur intervalle commun
(ou un pas propre) ; nan hors de cet intervalle, pas d'extrapolation ; trous comblés et
signaux plus lents signalés. Unité : saisie, sinon déduite de la formule (analyse
dimensionnelle de formules ; deriv / integ divisent / multiplient par s).
"""
from dataclasses import asdict, dataclass, field

import numpy as np
import formules
from formules import FormulaError, Interpreter, units
from formules.nodes import FuncNode

TIME_NAMES = ("time", "t")
AUTO, PERIOD = "auto", "period"
MAX_POINTS = 2_000_000
# nom -> (nombres d'arguments admis, description)
EXTRA_FUNCTIONS = {
    "deriv": ((1,), "dérivée"),
    "integ": ((1, 3), "intégrale cumulée, ou entre t1 et t2"),
    "mean": ((1, 3), "moyenne pondérée par le temps"),
    "rms": ((1, 3), "valeur efficace"),
    "pkpk": ((1, 3), "crête-crête"),
    "movavg": ((2,), "moyenne glissante sur n points"),
}
FUNCTIONS_HELP = (
    "Signaux entre crochets : [Vce], [Graphique:Courbe] ; time ou t : temps (s). "
    "Fonctions : sin cos tan exp log log10 sqrt abs ; max min sum avg ; interp, steps ; "
    + " ; ".join(f"{n} ({t})" for n, (_, t) in EXTRA_FUNCTIONS.items())
    + ". Arguments séparés par « ; » (integ(x; t1; t2)), nombres en unités SI (2e-6).")


@dataclass
class Signal:
    """Courbe en unités physiques : abscisses croissantes (temps), valeurs, unité."""
    name: str
    t: np.ndarray
    y: np.ndarray
    unit: str = ""
    source: str = ""
    color: str = "#808080"


@dataclass
class ComputedCurve:
    """Voie calculée d'un composant (enregistrée dans le projet)."""
    name: str = "M1"
    formula: str = ""
    unit: str = ""                     # vide : déduite de la formule
    base: str = AUTO                   # AUTO : signal le plus fin ; PERIOD : pas propre
    period: float = 1e-8               # s
    color: str = "#ff8c00"
    visible: bool = True

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "ComputedCurve":
        keys = cls.__dataclass_fields__
        return cls(**{k: v for k, v in data.items() if k in keys})


@dataclass
class Result:
    """Résultat d'une voie calculée : signal, ou nombre (integ(x; t1; t2)...) ; erreur."""
    name: str
    t: np.ndarray | None = None
    y: np.ndarray | None = None
    value: float | None = None         # résultat scalaire
    unit: str = ""
    error: str = ""
    warnings: list = field(default_factory=list)
    color: str = "#ff8c00"

    @property
    def ok(self) -> bool:
        return not self.error

    @property
    def signal(self) -> Signal | None:
        if self.y is None or self.t is None:
            return None
        return Signal(self.name, self.t, self.y, self.unit, "calcul", self.color)


# ================================================================ signaux d'un composant
def component_signals(component) -> dict:
    """
    Signaux d'un composant : clé de la formule -> Signal. Chaque courbe d'un graphique
    calibré : « Graphique:Courbe », et « Graphique » s'il n'a qu'une courbe, « Courbe » si
    son nom est unique dans le composant.
    """
    out, counts = {}, {}
    curves = []
    for graph in component.graphs:
        if graph.calibration is None:
            continue
        usable = [d for d in graph.datasets if len(d.pixels) >= 2]
        for dataset in usable:
            data = dataset.data(graph.calibration)
            order = np.argsort(data[:, 0], kind="stable")
            t, y = data[order, 0], data[order, 1]
            keep = np.r_[True, np.diff(t) > 0]          # abscisses strictement croissantes
            signal = Signal(dataset.name, t[keep], y[keep], graph.y_axis.unit,
                            f"{graph.name}:{dataset.name}", dataset.color)
            curves.append((graph, dataset, signal, len(usable)))
            counts[dataset.name] = counts.get(dataset.name, 0) + 1
    for graph, dataset, signal, n in curves:
        out[f"{graph.name}:{dataset.name}"] = signal
        if n == 1:
            out.setdefault(graph.name, signal)
    for graph, dataset, signal, n in curves:
        if counts[dataset.name] == 1:
            out.setdefault(dataset.name, signal)
    return out


def _key(name: str) -> str:
    return " ".join(name.split()).casefold()


def _find(signals: dict, name: str):
    """Signal désigné (nom exact, sinon sans casse ni espaces multiples)."""
    if name in signals:
        return signals[name]
    wanted = _key(name)
    return next((s for k, s in signals.items() if _key(k) == wanted), None)


# ================================================================ interprète
def _window(t, y, t1, t2):
    """Points de (t, y) entre t1 et t2, bornes comprises (valeurs interpolées)."""
    t1, t2 = sorted((float(t1), float(t2)))
    inside = (t > t1) & (t < t2)
    ends = np.interp([t1, t2], t, y, left=np.nan, right=np.nan)
    return np.r_[t1, t[inside], t2], np.r_[ends[0], y[inside], ends[1]]


def _trapz(t, y):
    ok = np.isfinite(y)
    t, y = t[ok], y[ok]
    if len(t) < 2:
        return np.nan
    return float(np.sum((y[1:] + y[:-1]) / 2 * np.diff(t)))


class SignalInterpreter(Interpreter):
    """Interprète de formules + fonctions qui ont besoin du temps réel des points."""

    def __init__(self, t: np.ndarray):
        super().__init__()
        self.t = t

    def visit_FuncNode(self, node: FuncNode):
        name = node.func.lower()
        if name not in EXTRA_FUNCTIONS:
            return super().visit_FuncNode(node)
        arities, _ = EXTRA_FUNCTIONS[name]
        args = [self.visit(a).value for a in node.args]
        if len(args) not in arities:
            raise FormulaError(f"La fonction « {name} » attend "
                               f"{' ou '.join(str(a) for a in arities)} argument(s), "
                               f"{len(args)} donné(s)")
        if np.ndim(args[0]) == 0:
            raise FormulaError(f"La fonction « {name} » s'applique à un signal, pas à un nombre")
        t = self.t
        if name == "movavg":
            n = args[1]
            if np.ndim(n) != 0 or n < 1 or n != int(n):
                raise FormulaError("movavg(x; n) : n doit être un entier >= 1")
            kernel = np.ones(int(n))
            return self.compute(name, lambda x: np.convolve(x[0], kernel, "same")
                                / np.convolve(np.ones_like(x[0]), kernel, "same"), args)
        if name == "deriv":
            return self.compute(name, lambda x: np.gradient(x[0], t), args)
        if len(args) == 3:
            if np.ndim(args[1]) or np.ndim(args[2]):
                raise FormulaError(f"{name}(x; t1; t2) : t1 et t2 sont des instants (nombres)")
            tt, yy = _window(t, np.asarray(args[0], float), args[1], args[2])
        else:
            tt, yy = t, np.asarray(args[0], float)
        if name == "integ" and len(args) == 1:
            def cumulative(x):
                y = np.nan_to_num(np.asarray(x[0], float))
                return np.r_[0.0, np.cumsum((y[1:] + y[:-1]) / 2 * np.diff(t))]
            return self.compute(name, cumulative, args)
        span = tt[-1] - tt[0]
        if name == "integ":
            return self.compute(name, lambda _: _trapz(tt, yy), args)
        if name == "mean":
            return self.compute(name, lambda _: _trapz(tt, yy) / span, args)
        if name == "rms":
            return self.compute(name, lambda _: np.sqrt(_trapz(tt, yy ** 2) / span), args)
        return self.compute(name, lambda _: np.nanmax(yy) - np.nanmin(yy), args)   # pkpk


# ================================================================ unités
class _Analyser(units._Analyser):
    """Analyse des unités de formules + fonctions ajoutées (comme loggerFPGA) et « t »."""

    def visit(self, node):
        if isinstance(node, formules.VariableNode) and node.name in TIME_NAMES:
            return units.Unit(units.parse_unit("s").dims, text="s")
        return super().visit(node)

    def function(self, node):
        name = node.func.lower()
        if name not in EXTRA_FUNCTIONS:
            return super().function(node)
        arg = self.visit(node.args[0]) if node.args else None
        if arg is None:
            return None
        if name in ("deriv", "integ"):
            sign = -1 if name == "deriv" else 1
            dims = list(arg.dims)
            dims[units.BASE_SYMBOLS.index("s")] += sign
            dims = tuple(dims)
            if dims == units.NO_DIM:
                return units.Unit(dims)
            named = units._named_dims().get(dims)
            if named:                                       # W·s -> J
                return units.Unit(dims, text=named[0])
            base = arg.text or units.dims_text(arg.dims)
            base = f"({base})" if any(c in base for c in "/·") else base
            return units.Unit(dims, text=f"{base}/s" if name == "deriv" else f"{base}·s")
        return arg if not arg.literal else units.DIMENSIONLESS


def deduce_unit(tree, input_units: dict) -> tuple:
    """(unité déduite ou « », remarques) de la formule."""
    analyser = _Analyser(input_units)
    unit = analyser.visit(tree)
    if analyser.issues or unit is None:
        return "", analyser.issues + analyser.notes
    if unit.literal or unit.dimensionless:
        return "", analyser.notes
    return unit.text or units.dims_text(unit.dims), analyser.notes


# ================================================================ évaluation
def _base(curve: ComputedCurve, inputs: list, everything: list) -> tuple:
    """Base de temps : (abscisses, avertissements)."""
    pool = inputs or everything
    if not pool:
        raise FormulaError("aucun signal : il faut un graphique calibré")
    lo = max(s.t[0] for s in pool) if inputs else min(s.t[0] for s in pool)
    hi = min(s.t[-1] for s in pool) if inputs else max(s.t[-1] for s in pool)
    if hi <= lo:
        raise FormulaError("les signaux utilisés n'ont pas d'intervalle de temps commun")
    if curve.base == PERIOD:
        count = (hi - lo) / curve.period
        if count > MAX_POINTS:
            raise FormulaError(f"pas trop fin : {count:,.0f} points (au plus {MAX_POINTS:,})")
        return np.arange(lo, hi + curve.period / 2, curve.period), []
    finest = min(pool, key=lambda s: np.median(np.diff(s.t)) if len(s.t) > 1 else np.inf)
    t = finest.t[(finest.t >= lo) & (finest.t <= hi)]
    if len(t) < 2:
        t = np.linspace(lo, hi, 1000)
    return t, []


def _on_base(signal: Signal, t: np.ndarray, warnings: list) -> np.ndarray:
    """Signal interpolé sur la base de temps (nan hors de son intervalle)."""
    if signal.t.shape == t.shape and np.array_equal(signal.t, t):
        return signal.y
    steps = np.diff(signal.t)
    if len(steps) and len(t) > 1:
        if np.median(steps) > 1.5 * np.median(np.diff(t)):
            warnings.append(f"[{signal.name}] : échantillonnage plus lent que la base de "
                            "temps, valeurs interpolées")
        if steps.max() > 5 * np.median(steps):
            warnings.append(f"[{signal.name}] : trous (parties cachées) comblés par "
                            "interpolation")
    return np.interp(t, signal.t, signal.y, left=np.nan, right=np.nan)


def evaluate(curve: ComputedCurve, signals: dict) -> Result:
    """Une voie calculée sur les signaux donnés (clé -> Signal)."""
    result = Result(curve.name, color=curve.color)
    if not curve.formula.strip():
        result.error = "formule vide"
        return result
    try:
        tree = formules.parse(curve.formula)
        names, channels = formules.references(tree)
        used = {}
        for ref in channels:
            signal = _find(signals, ref)
            if signal is None:
                known = ", ".join(f"[{k}]" for k in signals if ":" not in k) or "aucun"
                raise FormulaError(f"signal inconnu : [{ref}] (signaux : {known})")
            used[f"[{ref}]"] = signal
        for name in names:
            if name in TIME_NAMES:
                continue
            signal = _find(signals, name)
            if signal is None:
                raise FormulaError(f"nom inconnu : {name} (signaux entre crochets : [{name}])")
            used[name] = signal
        unique = list({id(s): s for s in used.values()}.values())
        t, warnings = _base(curve, unique, list({id(s): s for s in signals.values()}.values()))
        variables = {key: _on_base(signal, t, warnings) for key, signal in used.items()}
        for name in TIME_NAMES:
            variables[name] = t
        interpreter = SignalInterpreter(t)
        interpreter.vars.update(variables)
        value = interpreter.visit(tree).value
        unit, notes = deduce_unit(tree, {k: s.unit for k, s in used.items()})
        result.unit = curve.unit.strip() or unit
        result.warnings = list(dict.fromkeys(warnings)) + [n for n in notes if "SI" in n]
        if np.ndim(value) == 0:
            result.value = float(value)
        else:
            y = np.asarray(value, float)
            if y.shape != t.shape:
                raise FormulaError(f"la formule donne {y.size} valeurs pour {t.size} instants")
            result.t, result.y = t, y
    except FormulaError as error:
        result.error = str(error)
    return result


def evaluate_all(curves: list, signals: dict) -> list:
    """
    Voies calculées dans l'ordre : chacune peut utiliser les signaux et les voies
    calculées plus haut (par leur nom). Rend [Result].
    """
    available = dict(signals)
    out = []
    for curve in curves:
        if curve.name in signals:
            result = Result(curve.name, error=f"nom déjà pris par une courbe : {curve.name}")
        else:
            result = evaluate(curve, available)
        out.append(result)
        if result.signal is not None:
            available[curve.name] = result.signal
    return out

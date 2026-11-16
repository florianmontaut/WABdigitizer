# model/fit.py
"""
Ajustement d'un modèle sur les points d'une courbe.

Le modèle est une formule du paquet formules, fonction de x : « a*x^b », « r0 + k*x »,
« a*(1 - exp(-x/tau)) »... Les noms autres que x (et les constantes pi, e) sont les
paramètres ajustés. Le résultat se réécrit en formule numérique, réutilisable telle quelle
dans le logiciel de dimensionnement.
"""
import re
from dataclasses import dataclass, field

import numpy as np

import formules
from formules import FormulaError

VARIABLE = "x"

# modèles proposés (le texte reste modifiable)
PRESETS = {
    "Linéaire": "a*x + b",
    "Polynôme 2": "c0 + c1*x + c2*x^2",
    "Polynôme 3": "c0 + c1*x + c2*x^2 + c3*x^3",
    "Puissance": "a*x^b",
    "Puissance + seuil (Vce(Ic))": "v0 + r*x + k*x^b",
    "Exponentielle": "a*exp(b*x)",
    "1er ordre": "a*(1 - exp(-x/tau))",
    "Logarithme": "a + b*log(x)",
}


@dataclass
class FitResult:
    formula: str                       # modèle littéral
    parameters: dict                   # nom -> valeur ajustée
    rmse: float                        # écart quadratique moyen (unités de y)
    max_relative_error: float          # écart relatif maximal (|y| > 0)
    r2: float
    relative: bool = False
    errors: dict = field(default_factory=dict)   # écart-type estimé des paramètres

    def numeric_formula(self) -> str:
        """Formule avec les valeurs ajustées à la place des paramètres."""
        formules.parse(self.formula)
        values = {name: _fmt(value) for name, value in self.parameters.items()}
        return _substitute(self.formula, values)

    def evaluate(self, x):
        return evaluate(self.formula, self.parameters, x)

    def to_dict(self) -> dict:
        return {"formula": self.formula, "parameters": dict(self.parameters),
                "rmse": self.rmse, "max_relative_error": self.max_relative_error,
                "r2": self.r2, "relative": self.relative, "errors": dict(self.errors),
                "numeric": self.numeric_formula()}

    @classmethod
    def from_dict(cls, data: dict) -> "FitResult":
        return cls(formula=data["formula"], parameters=dict(data["parameters"]),
                   rmse=data.get("rmse", float("nan")),
                   max_relative_error=data.get("max_relative_error", float("nan")),
                   r2=data.get("r2", float("nan")), relative=data.get("relative", False),
                   errors=dict(data.get("errors", {})))


def _fmt(value: float) -> str:
    text = format(float(value), ".6g")
    return f"({text})" if text.startswith("-") else text


def _substitute(text: str, values: dict) -> str:
    """Remplace les identifiants par leur valeur (noms entiers, hors appels de fonction)."""
    out, position = [], 0
    for match in re.finditer(r"[A-Za-z_][A-Za-z_0-9]*", text):
        name = match.group(0)
        # un nom suivi de « ( » est une fonction (exp, log...)
        following = text[match.end():].lstrip()
        if name in values and not following.startswith("("):
            out.append(text[position:match.start()])
            out.append(values[name])
            position = match.end()
    out.append(text[position:])
    return "".join(out)


def parameters_of(formula: str) -> list:
    """Paramètres d'un modèle (noms autres que x), triés. FormulaError si invalide."""
    tree = formules.parse(formula)
    names, channels = formules.references(tree)
    if channels:
        raise FormulaError("un modèle ne cite pas de voie entre crochets")
    if VARIABLE not in names:
        raise FormulaError("le modèle doit dépendre de x")
    return sorted(names - {VARIABLE})


def evaluate(formula: str, parameters: dict, x) -> np.ndarray:
    tree = formules.parse(formula)
    x = np.asarray(x, dtype=float)
    value = formules.evaluate(tree, {VARIABLE: x, **parameters})
    return np.broadcast_to(np.asarray(value, dtype=float), x.shape).copy()


def _initial_guess(formula, names, x, y):
    """Valeurs de départ : 1, et pour les polynômes / lois linéaires, moindres carrés."""
    guess = {name: 1.0 for name in names}
    # paramètres « linéaires » : le modèle est linéaire en eux si la dérivée seconde est
    # nulle ; on tente une résolution linéaire, qui donne un bon départ dans ce cas
    try:
        base = evaluate(formula, {n: 0.0 for n in names}, x)
        columns = []
        for name in names:
            unit = {n: 0.0 for n in names}
            unit[name] = 1.0
            columns.append(evaluate(formula, unit, x) - base)
        matrix = np.column_stack(columns)
        if np.all(np.isfinite(matrix)) and np.all(np.isfinite(base)):
            solution, *_ = np.linalg.lstsq(matrix, y - base, rcond=None)
            trial = dict(zip(names, solution))
            if np.allclose(evaluate(formula, trial, x), base + matrix @ solution,
                           rtol=1e-6, atol=1e-9 * (np.abs(y).max() + 1)):
                return trial
    except (FormulaError, np.linalg.LinAlgError, ValueError):
        pass
    return guess


def fit(formula: str, x, y, initial: dict | None = None, relative: bool = False) -> FitResult:
    """
    Ajuste les paramètres de formula sur les points (x, y). relative : minimise l'écart
    relatif (courbes sur plusieurs décades, axe Y logarithmique).
    """
    from scipy.optimize import curve_fit

    names = parameters_of(formula)
    if not names:
        raise FormulaError("le modèle n'a aucun paramètre à ajuster")
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    keep = np.isfinite(x) & np.isfinite(y)
    x, y = x[keep], y[keep]
    if len(x) < len(names):
        raise FormulaError(f"{len(names)} paramètres demandent au moins {len(names)} points")
    tree = formules.parse(formula)

    def model(xs, *values):
        with np.errstate(all="ignore"):
            try:
                result = formules.evaluate(tree, {VARIABLE: xs, **dict(zip(names, values))})
            except FormulaError:
                return np.full_like(xs, 1e30)
        result = np.broadcast_to(np.asarray(result, dtype=float), xs.shape)
        return np.where(np.isfinite(result), result, 1e30)

    start = _initial_guess(formula, names, x, y)
    if initial:
        start.update({k: v for k, v in initial.items() if k in start})
    p0 = [start[name] for name in names]
    sigma = np.maximum(np.abs(y), 1e-12 * max(np.abs(y).max(), 1e-300)) if relative else None
    try:
        values, covariance = curve_fit(model, x, y, p0=p0, sigma=sigma, maxfev=20000)
    except (RuntimeError, ValueError) as error:
        raise FormulaError(f"l'ajustement n'a pas convergé : {error}") from None

    predicted = model(x, *values)
    residual = y - predicted
    rmse = float(np.sqrt(np.mean(residual ** 2)))
    nonzero = np.abs(y) > 0
    max_rel = float(np.max(np.abs(residual[nonzero] / y[nonzero]))) if nonzero.any() else float("nan")
    total = np.sum((y - y.mean()) ** 2)
    r2 = float(1.0 - np.sum(residual ** 2) / total) if total > 0 else float("nan")
    with np.errstate(invalid="ignore"):
        deviations = np.sqrt(np.diag(covariance)) if np.ndim(covariance) == 2 else []
    return FitResult(formula=formula, parameters=dict(zip(names, map(float, values))),
                     rmse=rmse, max_relative_error=max_rel, r2=r2, relative=relative,
                     errors={n: float(d) for n, d in zip(names, deviations)})

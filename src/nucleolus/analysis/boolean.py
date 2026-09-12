"""Synchronous Boolean rules over logical steps, with persistent intervention clamps."""
from nucleolus.schemas.simulation import BooleanAnalysis, BooleanManifest, BooleanRun, StateFlip, StateVector


def execute(model: BooleanManifest, clamps: dict[str, int] | None = None, steps: int = 20) -> BooleanRun:
    if not 1 <= steps <= 20:
        raise ValueError("logical step budget must be between 1 and 20")
    values = {v.id: v.initial for v in model.variables}
    clamps = clamps or {}
    if set(clamps) - values.keys() or any(type(v) is not int or v not in (0, 1) for v in clamps.values()):
        raise ValueError("clamps must bind known variables to integer Boolean states")
    values.update(clamps)
    trajectory = [StateVector(step=0, values=values.copy())]
    seen = {tuple(sorted(values.items()))}
    for step in range(1, steps + 1):
        next_values = {}
        for rule in model.rules:
            inputs = [values[r] for r in rule.regulators]
            if rule.operation == "identity":
                state = inputs[0]
            elif rule.operation == "not":
                state = 1 - inputs[0]
            elif rule.operation == "and":
                state = int(all(inputs))
            elif rule.operation == "or":
                state = int(any(inputs))
            else:
                score = sum(s * v for s, v in zip(rule.signs, inputs))
                state = 1 if score > rule.threshold else 0 if score < rule.threshold else values[rule.target]
            next_values[rule.target] = state
        next_values.update(clamps)
        trajectory.append(StateVector(step=step, values=next_values.copy()))
        if next_values == values:
            return BooleanRun(completion="fixed_point", trajectory=trajectory, terminal=next_values)
        vector = tuple(sorted(next_values.items()))
        if vector in seen:
            return BooleanRun(completion="cycle", trajectory=trajectory, terminal=None)
        seen.add(vector)
        values = next_values
    return BooleanRun(completion="max_steps", trajectory=trajectory, terminal=None)


def compare(model: BooleanManifest, source_entity: str, intervention: str) -> BooleanAnalysis:
    if intervention not in {"knockout", "increase"}:
        raise ValueError("Partial decrease has no Boolean semantics; use an explicit knockout model.")
    variable = next((v for v in model.variables if v.entity_id == source_entity), None)
    if variable is None:
        raise ValueError("Intervention entity is not modeled.")
    baseline = execute(model)
    perturbed = execute(model, {variable.id: 0 if intervention == "knockout" else 1})
    flips = []
    if baseline.terminal is not None and perturbed.terminal is not None:
        flips = [StateFlip(variable_id=v.id, entity_id=v.entity_id, before=baseline.terminal[v.id],
                           after=perturbed.terminal[v.id]) for v in model.variables
                 if baseline.terminal[v.id] != perturbed.terminal[v.id]]
    return BooleanAnalysis(baseline=baseline, perturbed=perturbed, flips=flips, rules=model.rules,
                           assumptions=model.assumptions)

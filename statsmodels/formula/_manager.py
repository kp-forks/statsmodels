from __future__ import annotations

import os
from typing import Any, Literal, NamedTuple, Sequence

import numpy as np
import pandas as pd
from typing import Mapping
HAVE_PATSY = False
HAVE_FORMULAIC = False

DEFAULT_FORMULA_ENGINE = os.environ.get("SM_DEFAULT_FORMULA_ENGINE", None)
if DEFAULT_FORMULA_ENGINE not in ("formulaic", "patsy", None):
    raise ValueError(
        f"Invalid value for SM_DEFAULT_FORMULA_ENGINE: {DEFAULT_FORMULA_ENGINE}"
    )

try:
    import patsy
    import patsy.missing

    DEFAULT_FORMULA_ENGINE = DEFAULT_FORMULA_ENGINE or "patsy"
    class NAAction(patsy.missing.NAAction):
        # monkey-patch so we can handle missing values in 'extra' arrays later
        def _handle_NA_drop(self, values, is_NAs, origins):
            total_mask = np.zeros(is_NAs[0].shape[0], dtype=bool)
            for is_NA in is_NAs:
                total_mask |= is_NA
            good_mask = ~total_mask
            self.missing_mask = total_mask
            # "..." to handle 1- versus 2-dim indexing
            return [v[good_mask, ...] for v in values]

    HAVE_PATSY = True

except ImportError:
    DEFAULT_FORMULA_ENGINE = DEFAULT_FORMULA_ENGINE or "formulaic"

    class NAAction:
        def __init__(self, on_NA="", NA_types=("",)):
            pass


try:
    import formulaic  # noqa: F401
    import formulaic.utils.constraints

    HAVE_FORMULAIC = True
except ImportError:
    pass


class _FormulaOption:
    def __init__(self, default_engine: Literal["patsy", "formulaic"] | None = None):
        if default_engine is None:
            default_engine = DEFAULT_FORMULA_ENGINE

        self._formula_engine = default_engine
        self._allowed_options = tuple()
        if HAVE_PATSY:
            self._allowed_options += ("patsy",)
        if HAVE_FORMULAIC:
            self._allowed_options += ("formulaic",)
        self.ordering = "none"

    @property
    def formula_engine(self) -> Literal["patsy", "formulaic"]:
        return self._formula_engine

    @formula_engine.setter
    def formula_engine(self, value: Literal["patsy", "formulaic"]) -> None:
        if value not in self._allowed_options:
            msg = "Invalid formula engine option. Must be "
            if len(self._allowed_options) == 1:
                msg += f"{self._allowed_options[0]}"
            else:
                allowed = list(self._allowed_options)
                allowed[-1] = f"or {allowed[-1]}"
                if len(allowed) > 2:
                    msg += ", ".join(allowed)
                else:
                    msg += " ".join(allowed)
            raise ValueError(f"{msg}.")

        self._formula_engine = value

    @property
    def ordering(self):
        return self._ordering

    @ordering.setter
    def ordering(self, value: str):
        if value not in ("degree", "sort", "none"):
            raise ValueError(
                "Invalid ordering option. Must be 'degree', 'sort', or 'none'."
            )
        self._ordering = value


class _Default:
    def __init__(self, name=""):
        self._name = name

    def __str__(self):
        return self._name

    def __repr__(self):
        return self._name


_NoDefault = _Default("<no default value>")


class LinearConstraintValues(NamedTuple):
    constraint_matrix: np.ndarray
    constraint_values: np.ndarray
    variable_names: list[str]


class FormulaManager:
    """
    Abstraction class that provides a common interface to patsy and formulaic.

    Designed to aid in the transition from patsy to formulaic.

    Parameters
    ----------
    engine : {"patsy", "formulaic"} or None
        The formula engine to use. If None, the default engine, which appears
        in the attribute statsmodels.formula.formula_options.engine, is used.

    Raises
    ------
    ValueError
        If the selected engine is not available.
    """

    def __init__(self, engine: Literal["patsy", "formulaic"] | None = None):
        self._engine = self._get_engine(engine)
        self._spec = None

    def _get_engine(
        self, engine: Literal["patsy", "formulaic"] | None = None
    ) -> Literal["patsy", "formulaic"]:
        """
        Check user engine selection or get the default engine to use.

        Parameters
        ----------
        engine : {"patsy", "formulaic"} or None
            The formula engine to use. If None, the default engine, which appears
            in the attribute statsmodels.formula.formula_options.engine, is used.

        Returns
        -------
        engine : {"patsy", "formulaic"}
            The selected engine


        Raises
        ------
        ValueError
            If the selected engine is not available.
        """
        # Patsy for now, to be changed to a user-settable variable before release
        _engine: Literal["patsy", "formulaic"]

        if engine is not None:
            _engine = engine
        else:
            import statsmodels.formula

            _engine = statsmodels.formula.options.formula_engine

        assert _engine is not None
        if _engine not in ("patsy", "formulaic"):
            raise ValueError(
                f"Unknown engine: {_engine}. Only patsy and formulaic are supported."
            )
        # Ensure selected engine is available
        msg_base = " is not available. Please install patsy."
        if _engine == "patsy" and not HAVE_PATSY:
            raise ImportError(f"patsy {msg_base}.")
        if _engine == "formulaic" and not HAVE_FORMULAIC:
            raise ImportError(f"formulaic {msg_base}.")

        return _engine

    @property
    def engine(self):
        """Get the formula engine."""
        return self._engine

    @property
    def spec(self):
        """
        Get the model specification. Only available after calling get_arrays.
        """
        return self._spec

    def get_arrays(
        self,
        formula,
        data,
        eval_env=0,
        pandas=True,
        na_action=None,
    ) -> (
        np.ndarray
        | tuple[np.ndarray, np.ndarray]
        | pd.DataFrame
        | tuple[pd.DataFrame, pd.DataFrame]
    ):
        """
        Get the design matrix and response vector from the formula and data.

        Parameters
        ----------
        formula
        data
        eval_env
        pandas
        na_action

        Returns
        -------

        """
        if isinstance(eval_env, (int, np.integer)):
            eval_env = int(eval_env) + 1
        if self._engine == "patsy":
            return_type = "dataframe" if pandas else "matrix"
            kwargs = {}
            if na_action:
                kwargs["NA_action"] = na_action
            if (
                isinstance(
                    formula, (patsy.design_info.DesignInfo, patsy.desc.ModelDesc)
                )
                or "~" not in formula
                or formula.strip().startswith("~")
            ):
                output = patsy.dmatrix(
                    formula, data, eval_env=eval_env, return_type=return_type, **kwargs
                )
            else:  # "~" in formula:
                output = patsy.dmatrices(
                    formula, data, eval_env=eval_env, return_type=return_type, **kwargs
                )
            if isinstance(output, tuple):
                self._spec = output[1].design_info
            else:
                self._spec = output.design_info
            return output

        else:  # self._engine == "formulaic":
            import statsmodels.formula

            kwargs = {}
            if pandas:
                kwargs["output"] = "pandas"
            if na_action:
                kwargs["na_action"] = na_action

            _ordering = statsmodels.formula.options.ordering
            if isinstance(formula, self.model_spec_type):
                _formula = formula
            else:
                _formula = formulaic.formula.Formula(formula, _ordering=_ordering)
            if isinstance(data, dict):
                # Work around for no dict support in formulaic
                if all(np.isscalar(v) for v in data.values()):
                    # Handle dict of scalars
                    _data = pd.DataFrame(data, index=[0])
                else:
                    _data = pd.DataFrame(data)
            else:
                _data = data
            if isinstance(eval_env, (int, Mapping)) or not HAVE_PATSY:
                _eval_env = eval_env
            elif HAVE_PATSY:
                from patsy.eval import EvalEnvironment
                if isinstance(eval_env, EvalEnvironment):
                    ns = eval_env._namespaces
                    _eval_env = {}
                    for val in ns:
                        _eval_env.update(val)
                else:
                    _eval_env = eval_env
            else:
                _eval_env = eval_env
            if not isinstance(_eval_env, (int, dict)):
                raise TypeError('context (eval_env) must be an int or a dict.')

            output = formulaic.model_matrix(_formula, _data, context=_eval_env, **kwargs)
            if isinstance(output, formulaic.ModelMatrices):
                if (
                    len(output) == 2
                    and hasattr(output, "lhs")
                    and hasattr(output, "rhs")
                ):
                    self._spec = output.rhs.model_spec
                    return output.lhs, output.rhs
                else:
                    raise ValueError(
                        "The formula has produced matrices that are not currently supported."
                    )

            self._spec = output.model_spec

            return output

    def get_linear_constraints(
        self, constraints: np.ndarray | str | Sequence[str], variable_names: list[str]
    ):
        """
        Get the linear constraints from the constraints and variable names.

        Parameters
        ----------
        constraints
        variable_names

        Returns
        -------
        LinearConstraintValues
            The constraint matrix, constraint values, and variable names.
        """
        if self._engine == "patsy":
            from patsy.design_info import DesignInfo

            lc = DesignInfo(variable_names).linear_constraint(constraints)
            return LinearConstraintValues(
                constraint_matrix=lc.coefs,
                constraint_values=lc.constants,
                variable_names=lc.variable_names,
            )
        else:  # self._engine == "formulaic"

            # Handle list of constraints, which is not supported by formulaic
            if isinstance(constraints, list):
                if len(constraints) == 0:
                    raise ValueError("Constraints must be non-empty")

                if isinstance(constraints[0], str):
                    if not all(isinstance(c, str) for c in constraints):
                        raise ValueError(
                            "All constraints must be strings when passed as a list."
                        )
                    _constraints = ", ".join(str(v) for v in constraints)
                else:
                    _constraints = np.array(constraints)
            else:
                _constraints = constraints
            if isinstance(_constraints, tuple):
                _constraints = (_constraints[0], np.atleast_1d(np.squeeze(_constraints[1])))
            lc_f = formulaic.utils.constraints.LinearConstraints.from_spec(
                _constraints, variable_names=list(variable_names)
            )
            return LinearConstraintValues(
                constraint_matrix=lc_f.constraint_matrix,
                constraint_values=np.atleast_2d(lc_f.constraint_values).T,
                variable_names=lc_f.variable_names,
            )

    def get_empty_eval_env(self):
        """
        Get an empty evaluation environment.

        Returns
        -------
        {EvalEnvironment, dict}
            A formula-engine-dependent empty evaluation environment.
        """
        if self._engine == "patsy":
            from patsy.eval import EvalEnvironment

            return EvalEnvironment({})
        else:
            return {}

    @property
    def intercept_term(self):
        """
        Get the formula-engine-specific intercept term.

        Returns
        -------
        Term
            The intercept term.
        """
        if self._engine == "patsy":
            from patsy.desc import INTERCEPT

            return INTERCEPT
        else:
            from formulaic.parser.types.factor import Factor
            from formulaic.parser.types.term import Term

            return Term((Factor("1"),))

    def remove_intercept(self, terms):
        """
        Remove intercept from Patsy terms.

        Parameters
        ----------
        terms : list[Term]
            A list of terms that might have an intercept

        Returns
        -------
        list[Term]
            The terms with the intercept removed, if present.
        """
        intercept = self.intercept_term
        if intercept in terms:
            terms.remove(intercept)
        return terms

    def has_intercept(self, spec):
        """
        Check if the model specification has an intercept term.

        Parameters
        ----------
        spec

        Returns
        -------
        bool
            True if the model specification has an intercept term, False otherwise.
        """

        return self.intercept_term in spec.terms

    def intercept_idx(self, spec):
        """
        Returns boolean array index indicating which column holds the intercept.

        Parameters
        ----------
        spec

        Returns
        -------
        ndarray
            Boolean array index indicating which column holds the intercept.
        """
        from numpy import array

        intercept = self.intercept_term
        return array([intercept == i for i in spec.terms])

    def get_na_action(self, action: str = "drop", types: Sequence[Any] = _NoDefault):
        """
        Get the NA action for the formula engine.

        Parameters
        ----------
        action
        types

        Returns
        -------
        NAAction | str
            The formula-engine-specific NA action.

        Notes
        -----
        types is ignored when using formulaic.
        """
        types = ["None", "NaN"] if types is _NoDefault else types
        if self._engine == "patsy":
            return NAAction(on_NA=action, NA_types=types)
        else:
            return action

    def get_spec(self, formula):
        if self._engine == "patsy":
            return patsy.ModelDesc.from_formula(formula)
        else:
            return formulaic.Formula(formula)

    def get_column_names(self, spec_or_frame):
        if isinstance(spec_or_frame, self.model_spec_type):
            if self._engine == "patsy":
                return list(spec_or_frame.term_names)
            else:
                return list(spec_or_frame.column_names)

        frame = spec_or_frame
        return list(self.get_model_spec(frame).column_names)

    @property
    def model_spec_type(self):
        if self._engine == "patsy":
            return patsy.design_info.DesignInfo
        else:
            return formulaic.model_spec.ModelSpec

    def get_term_name_slices(self, frame):
        spec = self.get_model_spec(frame)
        if self._engine == "patsy":
            return spec.term_name_slices
        else:
            return spec.term_slices

    def get_model_spec(self, frame, optional=False):
        if self._engine == "patsy":
            if optional and not hasattr(frame, "design_info"):
                return None
            return frame.design_info
        else:
            if optional and not hasattr(frame, "model_spec"):
                return None
            return frame.model_spec

    def get_slice(self, model_spec, term):
        if self._engine == "patsy":
            return model_spec.slice(term)
        else:
            return model_spec.get_slice(term)

    def get_term_name(self, term):
        if self._engine == "patsy":
            return term.name()
        else:
            return str(term)

    def get_description(self, model_spec):
        if self._engine == "patsy":
            return model_spec.describe()
        else:
            return str(model_spec.formula)
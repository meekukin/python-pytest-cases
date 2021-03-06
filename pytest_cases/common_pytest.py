from __future__ import division

try:  # python 3.3+
    from inspect import signature, Parameter
except ImportError:
    from funcsigs import signature, Parameter  # noqa

from distutils.version import LooseVersion
from inspect import isgeneratorfunction, isclass

try:
    from typing import Union, Callable, Any, Optional, Tuple, Type  # noqa
except ImportError:
    pass

import pytest
from _pytest.python import Metafunc

from .common_mini_six import string_types
from .common_pytest_marks import make_marked_parameter_value, get_param_argnames_as_list, has_pytest_param, \
    get_pytest_parametrize_marks
from .common_pytest_lazy_values import is_lazy_value


# A decorator that will work to create a fixture containing 'yield', whatever the pytest version, and supports hooks
if LooseVersion(pytest.__version__) >= LooseVersion('3.0.0'):
    def pytest_fixture(hook=None, **kwargs):
        def _decorate(f):
            # call hook if needed
            if hook is not None:
                f = hook(f)

            # create the fixture
            return pytest.fixture(**kwargs)(f)
        return _decorate
else:
    def pytest_fixture(hook=None, name=None, **kwargs):
        """Generator-aware pytest.fixture decorator for legacy pytest versions"""
        def _decorate(f):
            if name is not None:
                # 'name' argument is not supported in this old version, use the __name__ trick.
                f.__name__ = name

            # call hook if needed
            if hook is not None:
                f = hook(f)

            # create the fixture
            if isgeneratorfunction(f):
                return pytest.yield_fixture(**kwargs)(f)
            else:
                return pytest.fixture(**kwargs)(f)
        return _decorate


def remove_duplicates(lst):
    dset = set()
    # relies on the fact that dset.add() always returns None.
    return [item for item in lst
            if item not in dset and not dset.add(item)]


def is_fixture(fixture_fun  # type: Any
               ):
    """
    Returns True if the provided function is a fixture

    :param fixture_fun:
    :return:
    """
    try:
        fixture_fun._pytestfixturefunction  # noqa
        return True
    except AttributeError:
        # not a fixture ?
        return False


def safe_isclass(obj  # type: object
                 ):
    # type: (...) -> bool
    """Ignore any exception via isinstance on Python 3."""
    try:
        return isclass(obj)
    except Exception:  # noqa
        return False


def assert_is_fixture(fixture_fun  # type: Any
                      ):
    """
    Raises a ValueError if the provided fixture function is not a fixture.

    :param fixture_fun:
    :return:
    """
    if not is_fixture(fixture_fun):
        raise ValueError("The provided fixture function does not seem to be a fixture: %s. Did you properly decorate "
                         "it ?" % fixture_fun)


def get_fixture_name(fixture_fun  # type: Union[str, Callable]
                     ):
    """
    Internal utility to retrieve the fixture name corresponding to the given fixture function.
    Indeed there is currently no pytest API to do this.

    Note: this function can receive a string, in which case it is directly returned.

    :param fixture_fun:
    :return:
    """
    if isinstance(fixture_fun, string_types):
        return fixture_fun
    assert_is_fixture(fixture_fun)
    try:  # pytest 3
        custom_fixture_name = fixture_fun._pytestfixturefunction.name  # noqa
    except AttributeError:
        try:  # pytest 2
            custom_fixture_name = fixture_fun.func_name  # noqa
        except AttributeError:
            custom_fixture_name = None

    if custom_fixture_name is not None:
        # there is a custom fixture name
        return custom_fixture_name
    else:
        obj__name = getattr(fixture_fun, '__name__', None)
        if obj__name is not None:
            # a function, probably
            return obj__name
        else:
            # a callable object probably
            return str(fixture_fun)


def get_fixture_scope(fixture_fun):
    """
    Internal utility to retrieve the fixture scope corresponding to the given fixture function .
    Indeed there is currently no pytest API to do this.

    :param fixture_fun:
    :return:
    """
    assert_is_fixture(fixture_fun)
    return fixture_fun._pytestfixturefunction.scope  # noqa
    # except AttributeError:
    #     # pytest 2
    #     return fixture_fun.func_scope


# ---------------- working on pytest nodes (e.g. Function)

def is_function_node(node):
    try:
        node.function  # noqa
        return True
    except AttributeError:
        return False


def get_parametrization_markers(fnode):
    """
    Returns the parametrization marks on a pytest Function node.
    :param fnode:
    :return:
    """
    if LooseVersion(pytest.__version__) >= LooseVersion('3.4.0'):
        return list(fnode.iter_markers(name="parametrize"))
    else:
        return list(fnode.parametrize)


def get_param_names(fnode):
    """
    Returns a list of parameter names for the given pytest Function node.
    parameterization marks containing several names are split

    :param fnode:
    :return:
    """
    p_markers = get_parametrization_markers(fnode)
    param_names = []
    for paramz_mark in p_markers:
        param_names += get_param_argnames_as_list(paramz_mark.args[0])
    return param_names


# ---------- test ids utils ---------
def combine_ids(paramid_tuples):
    """
    Receives a list of tuples containing ids for each parameterset.
    Returns the final ids, that are obtained by joining the various param ids by '-' for each test node

    :param paramid_tuples:
    :return:
    """
    #
    return ['-'.join(pid for pid in testid) for testid in paramid_tuples]


def make_test_ids(global_ids, id_marks, argnames=None, argvalues=None, precomputed_ids=None):
    """
    Creates the proper id for each test based on (higher precedence first)

     - any specific id mark from a `pytest.param` (`id_marks`)
     - the global `ids` argument of pytest parametrize (`global_ids`)
     - the name and value of parameters (`argnames`, `argvalues`) or the precomputed ids(`precomputed_ids`)

    See also _pytest.python._idvalset method

    :param global_ids:
    :param id_marks:
    :param argnames:
    :param argvalues:
    :param precomputed_ids:
    :return:
    """
    if global_ids is not None:
        # overridden at global pytest.mark.parametrize level - this takes precedence.
        try:  # an explicit list of ids ?
            p_ids = list(global_ids)
        except TypeError:  # a callable to apply on the values
            p_ids = list(global_ids(v) for v in argvalues)
    else:
        # default: values-based
        if precomputed_ids is not None:
            if argnames is not None or argvalues is not None:
                raise ValueError("Only one of `precomputed_ids` or argnames/argvalues should be provided.")
            p_ids = precomputed_ids
        else:
            p_ids = make_test_ids_from_param_values(argnames, argvalues)

    # Finally, local pytest.param takes precedence over everything else
    for i, _id in enumerate(id_marks):
        if _id is not None:
            p_ids[i] = _id
    return p_ids


def make_test_ids_from_param_values(param_names,
                                    param_values,
                                    ):
    """
    Replicates pytest behaviour to generate the ids when there are several parameters in a single `parametrize.
    Note that param_values should not contain marks.

    :param param_names:
    :param param_values:
    :return: a list of param ids
    """
    if isinstance(param_names, string_types):
        raise TypeError("param_names must be an iterable. Found %r" % param_names)

    nb_params = len(param_names)
    if nb_params == 0:
        raise ValueError("empty list provided")
    elif nb_params == 1:
        paramids = []
        for _idx, v in enumerate(param_values):
            _id = mini_idvalset(param_names, (v,), _idx)
            paramids.append(_id)
    else:
        paramids = []
        for _idx, vv in enumerate(param_values):
            if len(vv) != nb_params:
                raise ValueError("Inconsistent lenghts for parameter names and values: '%s' and '%s'"
                                 "" % (param_names, vv))
            _id = mini_idvalset(param_names, vv, _idx)
            paramids.append(_id)
    return paramids


# ---- ParameterSet api ---
def analyze_parameter_set(pmark=None, argnames=None, argvalues=None, ids=None, check_nb=True):
    """
    analyzes a parameter set passed either as a pmark or as distinct
    (argnames, argvalues, ids) to extract/construct the various ids, marks, and
    values

    See also pytest.Metafunc.parametrize method, that calls in particular
    pytest.ParameterSet._for_parametrize and _pytest.python._idvalset

    :param pmark:
    :param argnames:
    :param argvalues:
    :param ids:
    :param check_nb: a bool indicating if we should raise an error if len(argnames) > 1 and any argvalue has
         a different length than len(argnames)
    :return: ids, marks, values
    """
    if pmark is not None:
        if any(a is not None for a in (argnames, argvalues, ids)):
            raise ValueError("Either provide a pmark OR the details")
        argnames = pmark.param_names
        argvalues = pmark.param_values
        ids = pmark.param_ids

    # extract all parameters that have a specific configuration (pytest.param())
    custom_pids, p_marks, p_values = extract_parameterset_info(argnames, argvalues, check_nb=check_nb)

    # get the ids by merging/creating the various possibilities
    p_ids = make_test_ids(argnames=argnames, argvalues=p_values, global_ids=ids, id_marks=custom_pids)

    return p_ids, p_marks, p_values


def extract_parameterset_info(argnames, argvalues, check_nb=True):
    """

    :param argnames: the names in this parameterset
    :param argvalues: the values in this parameterset
    :param check_nb: a bool indicating if we should raise an error if len(argnames) > 1 and any argvalue has
         a different length than len(argnames)
    :return:
    """
    pids = []
    pmarks = []
    pvalues = []
    if isinstance(argnames, string_types):
        raise TypeError("argnames must be an iterable. Found %r" % argnames)
    nbnames = len(argnames)
    for v in argvalues:
        _pid, _pmark, _pvalue = extract_pset_info_single(nbnames, v)

        pids.append(_pid)
        pmarks.append(_pmark)
        pvalues.append(_pvalue)

        if check_nb and nbnames > 1 and (len(_pvalue) != nbnames):
            raise ValueError("Inconsistent number of values in pytest parametrize: %s items found while the "
                             "number of parameters is %s: %s." % (len(_pvalue), nbnames, _pvalue))

    return pids, pmarks, pvalues


def extract_pset_info_single(nbnames, argvalue):
    """Return id, marks, value"""
    if is_marked_parameter_value(argvalue):
        # --id
        _id = get_marked_parameter_id(argvalue)
        # --marks
        marks = get_marked_parameter_marks(argvalue)
        # --value(a tuple if this is a tuple parameter)
        argvalue = get_marked_parameter_values(argvalue)
        return _id, marks, argvalue[0] if nbnames == 1 else argvalue
    else:
        # normal argvalue
        return None, None, argvalue


try:  # pytest 3.x+
    from _pytest.mark import ParameterSet  # noqa

    def is_marked_parameter_value(v):
        return isinstance(v, ParameterSet)

    def get_marked_parameter_marks(v):
        return v.marks

    def get_marked_parameter_values(v):
        return v.values

    def get_marked_parameter_id(v):
        return v.id

except ImportError:  # pytest 2.x
    from _pytest.mark import MarkDecorator

    # noinspection PyPep8Naming
    def ParameterSet(values,
                     id,  # noqa
                     marks):
        """ Dummy function (not a class) used only by parametrize_plus """
        if id is not None:
            raise ValueError("This should not happen as `pytest.param` does not exist in pytest 2")

        # smart unpack is required for compatibility
        val = values[0] if len(values) == 1 else values
        nbmarks = len(marks)

        if nbmarks == 0:
            return val
        elif nbmarks > 1:
            raise ValueError("Multiple marks on parameters not supported for old versions of pytest")
        else:
            # decorate with the MarkDecorator
            return marks[0](val)

    def is_marked_parameter_value(v):
        return isinstance(v, MarkDecorator)

    def get_marked_parameter_marks(v):
        return [v]

    def get_marked_parameter_values(v):
        if v.name in ('skip', 'skipif'):
            return v.args[-1]  # see MetaFunc.parametrize in pytest 2 to be convinced :)
        else:
            raise ValueError("Unsupported mark")

    def get_marked_parameter_id(v):
        return v.kwargs.get('id', None)


def get_pytest_nodeid(metafunc):
    try:
        return metafunc.definition.nodeid
    except AttributeError:
        return "unknown"


try:
    from _pytest.fixtures import scopes as pt_scopes
except ImportError:
    # pytest 2
    from _pytest.python import scopes as pt_scopes, Metafunc  # noqa


def get_pytest_scopenum(scope_str):
    return pt_scopes.index(scope_str)


def get_pytest_function_scopenum():
    return pt_scopes.index("function")


from _pytest.python import _idval  # noqa


if LooseVersion(pytest.__version__) >= LooseVersion('3.0.0'):
    _idval_kwargs = dict(idfn=None,
                         item=None,  # item is only used by idfn
                         config=None  # if a config hook was available it would be used before this is called)
                         )
else:
    _idval_kwargs = dict(idfn=None,
                         # item=None,  # item is only used by idfn
                         # config=None  # if a config hook was available it would be used before this is called)
                         )


def mini_idval(
        val,      # type: object
        argname,  # type: str
        idx,      # type: int
):
    """
    A simplified version of idval where idfn, item and config do not need to be passed.

    :param val:
    :param argname:
    :param idx:
    :return:
    """
    return _idval(val=val, argname=argname, idx=idx, **_idval_kwargs)


def mini_idvalset(argnames, argvalues, idx):
    """ mimic _pytest.python._idvalset """
    this_id = [
        _idval(val, argname, idx=idx, **_idval_kwargs)
        for val, argname in zip(argvalues, argnames)
    ]
    return "-".join(this_id)


try:
    from _pytest.compat import getfuncargnames  # noqa
except ImportError:
    import sys

    def num_mock_patch_args(function):
        """ return number of arguments used up by mock arguments (if any) """
        patchings = getattr(function, "patchings", None)
        if not patchings:
            return 0

        mock_sentinel = getattr(sys.modules.get("mock"), "DEFAULT", object())
        ut_mock_sentinel = getattr(sys.modules.get("unittest.mock"), "DEFAULT", object())

        return len(
            [p for p in patchings if not p.attribute_name and (p.new is mock_sentinel or p.new is ut_mock_sentinel)]
        )

    # noinspection SpellCheckingInspection
    def getfuncargnames(function, cls=None):
        """Returns the names of a function's mandatory arguments."""
        parameters = signature(function).parameters

        arg_names = tuple(
            p.name
            for p in parameters.values()
            if (
                    p.kind is Parameter.POSITIONAL_OR_KEYWORD
                    or p.kind is Parameter.KEYWORD_ONLY
            )
            and p.default is Parameter.empty
        )

        # If this function should be treated as a bound method even though
        # it's passed as an unbound method or function, remove the first
        # parameter name.
        if cls and not isinstance(cls.__dict__.get(function.__name__, None), staticmethod):
            arg_names = arg_names[1:]
        # Remove any names that will be replaced with mocks.
        if hasattr(function, "__wrapped__"):
            arg_names = arg_names[num_mock_patch_args(function):]
        return arg_names


class MiniFuncDef(object):
    __slots__ = ('nodeid',)

    def __init__(self, nodeid):
        self.nodeid = nodeid


class MiniMetafunc(Metafunc):
    # noinspection PyMissingConstructor
    def __init__(self, func):
        self.config = None
        self.function = func
        self.definition = MiniFuncDef(func.__name__)
        self._calls = []
        # non-default parameters
        self.fixturenames = getfuncargnames(func)
        # get parametrization marks
        self.pmarks = get_pytest_parametrize_marks(self.function)
        if self.is_parametrized:
            self.update_callspecs()
            self.required_fixtures = set(self.fixturenames) - set(self._calls[0].funcargs)
        else:
            self.required_fixtures = self.fixturenames

    @property
    def is_parametrized(self):
        return len(self.pmarks) > 0

    @property
    def requires_fixtures(self):
        return len(self.required_fixtures) > 0

    def update_callspecs(self):
        """

        :return:
        """
        for pmark in self.pmarks:
            if len(pmark.param_names) == 1:
                argvals = tuple(v if is_marked_parameter_value(v) else (v,) for v in pmark.param_values)
            else:
                argvals = pmark.param_values
            self.parametrize(argnames=pmark.param_names, argvalues=argvals, ids=pmark.param_ids,
                             # use indirect = False and scope = 'function' to avoid having to implement complex patches
                             indirect=False, scope='function')

        if not has_pytest_param:
            # fix the CallSpec2 instances so that the marks appear
            # noinspection PyProtectedMember
            for c in self._calls:
                c.marks = list(c.keywords.values())


def get_callspecs(func):
    """
    Returns a list of pytest CallSpec objects corresponding to calls that should be made for this parametrized function.
    This mini-helper assumes no complex things (scope='function', indirect=False, no fixtures, no custom configuration)

    :param func:
    :return:
    """
    meta = MiniMetafunc(func)
    # meta.update_callspecs()
    # noinspection PyProtectedMember
    return meta._calls


def cart_product_pytest(argnames, argvalues):
    """
     - do NOT use `itertools.product` as it fails to handle MarkDecorators
     - we also unpack tuples associated with several argnames ("a,b") if needed
     - we also propagate marks

    :param argnames:
    :param argvalues:
    :return:
    """
    # transform argnames into a list of lists
    argnames_lists = [get_param_argnames_as_list(_argnames) if len(_argnames) > 0 else [] for _argnames in argnames]

    # make the cartesian product per se
    argvalues_prod = _cart_product_pytest(argnames_lists, argvalues)

    # flatten the list of argnames
    argnames_list = [n for nlist in argnames_lists for n in nlist]

    # apply all marks to the arvalues
    argvalues_prod = [make_marked_parameter_value(tuple(argvalues), marks=marks) if len(marks) > 0 else tuple(argvalues)
                      for marks, argvalues in argvalues_prod]

    return argnames_list, argvalues_prod


def _cart_product_pytest(argnames_lists, argvalues):
    result = []

    # first perform the sub cartesian product with entries [1:]
    sub_product = _cart_product_pytest(argnames_lists[1:], argvalues[1:]) if len(argvalues) > 1 else None

    # then do the final product with entry [0]
    for x in argvalues[0]:
        # handle x
        nb_names = len(argnames_lists[0])

        # (1) extract meta-info
        x_id, x_marks, x_value = extract_pset_info_single(nb_names, x)
        x_marks_lst = list(x_marks) if x_marks is not None else []
        if x_id is not None:
            raise ValueError("It is not possible to specify a sub-param id when using the new parametrization style. "
                             "Either use the traditional style or customize all ids at once in `idgen`")

        # (2) possibly unpack
        if nb_names > 1:
            # if lazy value, we have to do something
            if is_lazy_value(x_value):
                x_value_lst = x_value.as_lazy_items_list(nb_names)
            else:
                x_value_lst = list(x_value)
        else:
            x_value_lst = [x_value]

        # product
        if len(argvalues) > 1:
            for m, p in sub_product:
                # combine marks and values
                result.append((x_marks_lst + m, x_value_lst + p))
        else:
            result.append((x_marks_lst, x_value_lst))

    return result

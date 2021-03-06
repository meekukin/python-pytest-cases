# Use true division operator always even in old python 2.x (used in `_extract_cases_from_module`)
from __future__ import division

from functools import partial
from importlib import import_module
from inspect import getmembers
import re
from warnings import warn

from pytest_cases import fixture

try:
    from typing import Union, Callable, Iterable, Any, Type, List, Tuple  # noqa
except ImportError:
    pass

from .common_mini_six import string_types
from .common_others import get_code_first_line, AUTO, AUTO2
from .common_pytest_marks import copy_pytest_marks, make_marked_parameter_value
from .common_pytest_lazy_values import lazy_value
from .common_pytest import safe_isclass, MiniMetafunc

from .case_funcs_new import matches_tag_query, is_case_function, is_case_class, CaseInfo, CASE_PREFIX_FUN
from .fixture_parametrize_plus import fixture_ref, _parametrize_plus

THIS_MODULE = object()
"""Singleton that can be used instead of a module name to indicate that the module is the current one"""

try:
    from typing import Literal  # noqa
    from types import ModuleType  # noqa

    ModuleRef = Union[str, ModuleType, Literal[AUTO], Literal[AUTO2], Literal[THIS_MODULE]]  # noqa

except:  # noqa
    pass


def parametrize_with_cases(argnames,                # type: str
                           cases=AUTO,              # type: Union[Callable, Type, ModuleRef]
                           prefix=CASE_PREFIX_FUN,  # type: str
                           glob=None,               # type: str
                           has_tag=None,            # type: Any
                           filter=None,             # type: Callable[[Callable], bool]  # noqa
                           **kwargs
                           ):
    # type: (...) -> Callable[[Callable], Callable]
    """
    A decorator for test functions or fixtures, to parametrize them based on test cases. It works similarly to
    `@pytest.mark.parametrize`: argnames represent a coma-separated string of arguments to inject in the decorated
    test function or fixture. The argument values (argvalues in `pytest.mark.parametrize`) are collected from the
    various case functions found according to `cases`, and injected as lazy values so that the case functions are called
    just before the test or fixture is executed.

    By default (`cases=AUTO`) the list of test cases is automatically drawn from the python module file named
    `test_<name>_cases.py` where `test_<name>` is the current module name. An alternate naming convention
    `cases_<name>.py` can be used by setting `cases=AUTO2`.

    Finally, the `cases` argument also accepts an explicit case function, cases-containing class, module or module name;
    or a list of such elements. Note that both absolute and relative module names are suported.

    Note that `@parametrize_with_cases` collection and parameter creation steps are strictly equivalent to
    `get_all_cases` + `get_parametrize_args`. This can be handy for debugging purposes.

    ```python
    # Collect all cases
    cases_funs = get_all_cases(f, cases=cases, prefix=prefix, glob=glob, has_tag=has_tag, filter=filter)

    # Transform the various functions found
    argvalues = get_parametrize_args(cases_funs, prefix=prefix)
    ```

    :param argnames: same than in @pytest.mark.parametrize
    :param cases: a case function, a class containing cases, a module object or a module name string (relative module
        names accepted). Or a list of such items. You may use `THIS_MODULE` or `'.'` to include current module.
        `AUTO` (default) means that the module named `test_<name>_cases.py` will be loaded, where `test_<name>.py` is
        the module file of the decorated function. `AUTO2` allows you to use the alternative naming scheme
        `case_<name>.py`. When a module is listed, all of its functions matching the `prefix`, `filter` and `has_tag`
        are selected, including those functions nested in classes following naming pattern `*Case*`. When classes are
        explicitly provided in the list, they can have any name and do not need to follow this `*Case*` pattern.
    :param prefix: the prefix for case functions. Default is 'case_' but you might wish to use different prefixes to
        denote different kind of cases, for example 'data_', 'algo_', 'user_', etc.
    :param glob: an optional glob-like pattern for case ids, for example "*_success" or "*_failure". Note that this
        is applied on the case id, and therefore if it is customized through `@case(id=...)` it should be taken into
        account.
    :param has_tag: a single tag or a tuple, set, list of tags that should be matched by the ones set with the `@case`
        decorator on the case function(s) to be selected.
    :param filter: a callable receiving the case function and returning True or a truth value in case the function
        needs to be selected.
    :return:
    """
    def _apply_parametrization(f):
        """ execute parametrization of test function or fixture `f` """

        # Collect all cases
        cases_funs = get_all_cases(f, cases=cases, prefix=prefix, glob=glob, has_tag=has_tag, filter=filter)

        # Transform the various functions found
        argvalues = get_parametrize_args(cases_funs)

        # Finally apply parametrization - note that we need to call the private method so that fixture are created in
        # the right module (not here)
        _parametrize_with_cases = _parametrize_plus(argnames, argvalues, **kwargs)
        return _parametrize_with_cases(f)

    return _apply_parametrization


def create_glob_name_filter(glob_str  # type: str
                            ):
    """
    Creates a glob-like matcher for the name of case functions

    :param case_fun:
    :return:
    """
    name_matcher = re.compile(glob_str.replace("*", ".*"))

    def _glob_name_filter(case_fun):
        case_fun_id = case_fun._pytestcase.id
        assert case_fun_id is not None
        return name_matcher.match(case_fun_id)

    return _glob_name_filter


def get_all_cases(parametrization_target,  # type: Callable
                  cases=None,              # type: Union[Callable, Type, ModuleRef]
                  prefix=CASE_PREFIX_FUN,  # type: str
                  glob=None,               # type: str
                  has_tag=None,            # type: Union[str, Iterable[str]]
                  filter=None              # type: Callable[[Callable], bool]  # noqa
                  ):
    # type: (...) -> List[Callable]
    """
    Lists all desired cases for a given `parametrization_target` (a test function or a fixture). This function may be
    convenient for debugging purposes. See `@parametrize_with_cases` for details on the parameters.

    :param parametrization_target: a test function
    :param cases: a case function, a class containing cases, a module or a module name string (relative module
        names accepted). Or a list of such items. You may use `THIS_MODULE` or `'.'` to include current module.
        `AUTO` (default) means that the module named `test_<name>_cases.py` will be loaded, where `test_<name>.py` is
        the module file of the decorated function. `AUTO2` allows you to use the alternative naming scheme
        `case_<name>.py`. When a module is listed, all of its functions matching the `prefix`, `filter` and `has_tag`
        are selected, including those functions nested in classes following naming pattern `*Case*`. When classes are
        explicitly provided in the list, they can have any name and do not need to follow this `*Case*` pattern.
    :param prefix: the prefix for case functions. Default is 'case_' but you might wish to use different prefixes to
        denote different kind of cases, for example 'data_', 'algo_', 'user_', etc.
    :param glob: an optional glob-like pattern for case ids, for example "*_success" or "*_failure". Note that this
        is applied on the case id, and therefore if it is customized through `@case(id=...)` it should be taken into
        account.
    :param has_tag: a single tag or a tuple, set, list of tags that should be matched by the ones set with the `@case`
        decorator on the case function(s) to be selected.
    :param filter: a callable receiving the case function and returning True or a truth value in case the function
        needs to be selected.
    """
    # Handle single elements
    if isinstance(cases, string_types):
        cases = (cases,)
    else:
        try:
            cases = tuple(cases)
        except TypeError:
            cases = (cases,)

    # validate prefix
    if not isinstance(prefix, str):
        raise TypeError("`prefix` should be a string, found: %r" % prefix)

    # validate glob and filter and merge them in a single tuple of callables
    filters = ()
    if glob is not None:
        if not isinstance(glob, string_types):
            raise TypeError("`glob` should be a string containing a glob-like pattern (not a regex).")

        filters += (create_glob_name_filter(glob),)
    if filter is not None:
        if not callable(filter):
            raise TypeError(
                "`filter` should be a callable starting in pytest-cases 0.8.0. If you wish to provide a single"
                " tag to match, use `has_tag` instead.")

        filters += (filter,)

    # parent package
    caller_module_name = getattr(parametrization_target, '__module__', None)
    parent_pkg_name = '.'.join(caller_module_name.split('.')[:-1]) if caller_module_name is not None else None

    # start collecting all cases
    cases_funs = []
    for c in cases:
        # load case or cases depending on type
        if safe_isclass(c):
            # class
            new_cases = extract_cases_from_class(c, case_fun_prefix=prefix, check_name=False)  # do not check name, it was explicitly passed
            cases_funs += new_cases
        elif callable(c):
            # function
            if is_case_function(c, check_prefix=False):  # do not check prefix, it was explicitly passed
                cases_funs.append(c)
            else:
                raise ValueError("Unsupported case function: %r" % c)
        else:
            # module
            if c is AUTO:
                c = import_default_cases_module(parametrization_target)
            elif c is AUTO2:
                c = import_default_cases_module(parametrization_target, alt_name=True)
            elif c is THIS_MODULE or c == '.':
                c = caller_module_name
            new_cases = extract_cases_from_module(c, package_name=parent_pkg_name, case_fun_prefix=prefix)
            cases_funs += new_cases

    # filter last, for easier debugging (collection will be slightly less performant when a large volume of cases exist)
    return [c for c in cases_funs
            # IMPORTANT: with the trick below we create and attach a case info on each `c` in the same loop
            if CaseInfo.get_from(c, create=True, prefix_for_ids=prefix)
            # this second member below is the only actual test performing query filtering
            and matches_tag_query(c, has_tag=has_tag, filter=filters)]


def get_parametrize_args(cases_funs,  # type: List[Callable]
                         ):
    # type: (...) -> List[Union[lazy_value, fixture_ref]]
    """
    Transforms a list of cases (obtained from `get_all_cases`) into a list of argvalues for `@parametrize`.
    Each case function `case_fun` is transformed into one or several `lazy_value`(s) or a `fixture_ref`:

     - If `case_fun` requires at least on fixture, a fixture will be created if not yet present, and a `fixture_ref`
       will be returned.
     - If `case_fun` is a parametrized case, one `lazy_value` with a partialized version will be created for each
       parameter combination.
     - Otherwise, `case_fun` represents a single case: in that case a single `lazy_value` is returned.

    :param cases_funs: a list of case functions returned typically by `get_all_cases`
    :return:
    """
    return [c for _f in cases_funs for c in case_to_argvalues(_f)]


def case_to_argvalues(case_fun,                # type: Callable
                      ):
    # type: (...) -> Tuple[lazy_value]
    """Transform a single case into one or several `lazy_value`(s) or a `fixture_ref` to be used in `@parametrize`

    If `case_fun` requires at least on fixture, a fixture will be created if not yet present, and a `fixture_ref` will
    be returned.

    If `case_fun` is a parametrized case, one `lazy_value` with a partialized version will be created for each parameter
    combination.

    Otherwise, `case_fun` represents a single case: in that case a single `lazy_value` is returned.

    :param case_fun:
    :return:
    """
    case_info = CaseInfo.get_from(case_fun)
    case_id = case_info.id
    case_marks = case_info.marks

    # get the list of all calls that pytest *would* have made for such a (possibly parametrized) function
    meta = MiniMetafunc(case_fun)

    if not meta.requires_fixtures:
        if not meta.is_parametrized:
            # single unparametrized case function
            return (lazy_value(case_fun, id=case_id, marks=case_marks),)
        else:
            # parametrized. create one version of the callable for each parametrized call
            return tuple(lazy_value(partial(case_fun, **c.funcargs), id="%s-%s" % (case_id, c.id), marks=c.marks)
                         for c in meta._calls)
    else:
        # at least a required fixture: create a fixture
        # unwrap any partial that would have been created by us because the fixture was in a class
        if isinstance(case_fun, partial):
            host_cls = case_fun.host_class
            case_fun = case_fun.func
        else:
            host_cls = None

        host_module = import_module(case_fun.__module__)

        # create a new fixture and place it on the host (note: if already done, no need to recreate it)
        existing_fix = getattr(host_cls or host_module, case_id, None)
        if existing_fix is None:
            # if meta.is_parametrized:
            #     nothing to do, the parametrization marks are already there
            new_fix = fixture(name=case_id)(case_fun)
            setattr(host_cls or host_module, case_id, new_fix)
        else:
            raise NotImplementedError("We should check if this is the same or another and generate a new name in that "
                                      "case")

        # now reference the new or existing fixture
        argvalues_tuple = (fixture_ref(case_id),)
        return make_marked_parameter_value(argvalues_tuple, marks=case_marks) if case_marks else argvalues_tuple


def import_default_cases_module(f, alt_name=False):
    """
    Implements the `module=AUTO` behaviour of `@parameterize_cases`: based on the decorated test function `f`,
    it finds its containing module name "<test_module>.py" and then tries to import the python module
    "<test_module>_cases.py".

    Alternately if `alt_name=True` the name pattern to use will be `cases_<module>.py` when the test module is named
    `test_<module>.py`.

    :param f: the decorated test function
    :param alt_name: a boolean (default False) to use the alternate naming scheme.
    :return:
    """
    if alt_name:
        parts = f.__module__.split('.')
        assert parts[-1][0:5] == 'test_'
        cases_module_name = "%s.cases_%s" % ('.'.join(parts[:-1]), parts[-1][5:])
    else:
        cases_module_name = "%s_cases" % f.__module__

    try:
        cases_module = import_module(cases_module_name)
    except ImportError:
        raise ValueError("Error importing test cases module to parametrize function %r: unable to import AUTO%s "
                         "cases module %r. Maybe you wish to import cases from somewhere else ? In that case please "
                         "specify `cases=...`."
                         % (f, '2' if alt_name else '', cases_module_name))
    return cases_module


def hasinit(obj):
    init = getattr(obj, "__init__", None)
    if init:
        return init != object.__init__


def hasnew(obj):
    new = getattr(obj, "__new__", None)
    if new:
        return new != object.__new__


class CasesCollectionWarning(UserWarning):
    """
    Warning emitted when pytest cases is not able to collect a file or symbol in a module.
    """
    __module__ = "pytest_cases"


def extract_cases_from_class(cls,
                             check_name=True,
                             case_fun_prefix=CASE_PREFIX_FUN,
                             _case_param_factory=None
                             ):
    # type: (...) -> List[Callable]
    """

    :param cls:
    :param check_name:
    :param case_fun_prefix:
    :param _case_param_factory:
    :return:
    """
    if is_case_class(cls, check_name=check_name):
        # see from _pytest.python import pytest_pycollect_makeitem

        if hasinit(cls):
            warn(
                CasesCollectionWarning(
                    "cannot collect cases class %r because it has a "
                    "__init__ constructor"
                    % (cls.__name__, )
                )
            )
            return []
        elif hasnew(cls):
            warn(
                CasesCollectionWarning(
                    "cannot collect test class %r because it has a "
                    "__new__ constructor"
                    % (cls.__name__, )
                )
            )
            return []

        return _extract_cases_from_module_or_class(cls=cls, case_fun_prefix=case_fun_prefix,
                                                   _case_param_factory=_case_param_factory)
    else:
        return []


def extract_cases_from_module(module,                           # type: ModuleRef
                              package_name=None,                # type: str
                              case_fun_prefix=CASE_PREFIX_FUN,  # type: str
                              _case_param_factory=None
                              ):
    # type: (...) -> List[Callable]
    """
    Internal method used to create a list of `CaseDataGetter` for all cases available from the given module.
    See `@cases_data`

    See also `_pytest.python.PyCollector.collect` and `_pytest.python.PyCollector._makeitem` and
    `_pytest.python.pytest_pycollect_makeitem`: we could probably do this in a better way in pytest_pycollect_makeitem

    :param module:
    :param package_name:
    :param _case_param_factory:
    :return:
    """
    # optionally import module if passed as module name string
    if isinstance(module, string_types):
        module = import_module(module, package=package_name)

    return _extract_cases_from_module_or_class(module=module, _case_param_factory=_case_param_factory,
                                               case_fun_prefix=case_fun_prefix)


def _extract_cases_from_module_or_class(module=None,                      # type: ModuleRef
                                        cls=None,                         # type: Type
                                        case_fun_prefix=CASE_PREFIX_FUN,  # type: str
                                        _case_param_factory=None
                                        ):
    """

    :param module:
    :param _case_param_factory:
    :return:
    """
    if not ((cls is None) ^ (module is None)):
        raise ValueError("Only one of cls or module should be provided")

    container = cls or module

    # We will gather all cases in the reference module and put them in this dict (line no, case)
    cases_dct = dict()

    # List members - only keep the functions from the module file (not the imported ones)
    if module is not None:
        def _of_interest(f):
            # check if the function is actually *defined* in this module (not imported from elsewhere)
            # Note: we used code.co_filename == module.__file__ in the past
            # but on some targets the file changes to a cached one so this does not work reliably,
            # see https://github.com/smarie/python-pytest-cases/issues/72
            try:
                return f.__module__ == module.__name__
            except:  # noqa
                return False
    else:
        def _of_interest(x):  # noqa
            return True

    for m_name, m in getmembers(container, _of_interest):
        if is_case_class(m):
            co_firstlineno = get_code_first_line(m)
            cls_cases = extract_cases_from_class(m, case_fun_prefix=case_fun_prefix, _case_param_factory=_case_param_factory)
            for _i, _m_item in enumerate(cls_cases):
                gen_line_nb = co_firstlineno + (_i / len(cls_cases))
                cases_dct[gen_line_nb] = _m_item

        elif is_case_function(m, prefix=case_fun_prefix):
            co_firstlineno = get_code_first_line(m)
            if cls is not None:
                if isinstance(cls.__dict__[m_name], (staticmethod, classmethod)):
                    # skip it
                    continue
                # partialize the function to get one without the 'self' argument
                new_m = partial(m, cls())
                # remember the class
                new_m.host_class = cls
                # we have to recopy all metadata concerning the case function
                new_m.__name__ = m.__name__
                CaseInfo.copy_info(m, new_m)
                copy_pytest_marks(m, new_m, override=True)
                m = new_m
                del new_m

            if _case_param_factory is None:
                # Nominal usage: put the case in the dictionary
                cases_dct[co_firstlineno] = m
            else:
                # Legacy usage where the cases generators were expanded here and inserted with a virtual line no
                _case_param_factory(m, co_firstlineno, cases_dct)

    # convert into a list, taking all cases in order of appearance in the code (sort by source code line number)
    cases = [cases_dct[k] for k in sorted(cases_dct.keys())]

    return cases


# Below is the beginning of a switch from our code scanning tool above to the same one than pytest.
# from .common_pytest import is_fixture, safe_isclass, compat_get_real_func, compat_getfslineno
#
#
# class PytestCasesWarning(UserWarning):
#     """
#     Bases: :class:`UserWarning`.
#
#     Base class for all warnings emitted by pytest cases.
#     """
#
#     __module__ = "pytest_cases"
#
#
# class PytestCasesCollectionWarning(PytestCasesWarning):
#     """
#     Bases: :class:`PytestCasesWarning`.
#
#     Warning emitted when pytest cases is not able to collect a file or symbol in a module.
#     """
#
#     __module__ = "pytest_cases"
#
#
# class CasesModule(object):
#     """
#     A collector for test cases
#     This is a very lightweight version of `_pytest.python.Module`,the pytest collector for test functions and classes.
#
#     See also pytest_collect_file and pytest_pycollect_makemodule hooks
#     """
#     __slots__ = 'obj'
#
#     def __init__(self, module):
#         self.obj = module
#
#     def collect(self):
#         """
#         A copy of pytest Module.collect (PyCollector.collect actually)
#         :return:
#         """
#         if not getattr(self.obj, "__test__", True):
#             return []
#
#         # NB. we avoid random getattrs and peek in the __dict__ instead
#         # (XXX originally introduced from a PyPy need, still true?)
#         dicts = [getattr(self.obj, "__dict__", {})]
#         for basecls in getmro(self.obj.__class__):
#             dicts.append(basecls.__dict__)
#         seen = {}
#         values = []
#         for dic in dicts:
#             for name, obj in list(dic.items()):
#                 if name in seen:
#                     continue
#                 seen[name] = True
#                 res = self._makeitem(name, obj)
#                 if res is None:
#                     continue
#                 if not isinstance(res, list):
#                     res = [res]
#                 values.extend(res)
#
#         def sort_key(item):
#             fspath, lineno, _ = item.reportinfo()
#             return (str(fspath), lineno)
#
#         values.sort(key=sort_key)
#         return values
#
#     def _makeitem(self, name, obj):
#         """ An adapted copy of _pytest.python.pytest_pycollect_makeitem """
#         if safe_isclass(obj):
#             if self.iscaseclass(obj, name):
#                 raise ValueError("Case classes are not yet supported: %r" % obj)
#         elif self.iscasefunction(obj, name):
#             # mock seems to store unbound methods (issue473), normalize it
#             obj = getattr(obj, "__func__", obj)
#             # We need to try and unwrap the function if it's a functools.partial
#             # or a functools.wrapped.
#             # We mustn't if it's been wrapped with mock.patch (python 2 only)
#             if not (isfunction(obj) or isfunction(compat_get_real_func(obj))):
#                 filename, lineno = compat_getfslineno(obj)
#                 warn_explicit(
#                     message=PytestCasesCollectionWarning(
#                         "cannot collect %r because it is not a function." % name
#                     ),
#                     category=None,
#                     filename=str(filename),
#                     lineno=lineno + 1,
#                 )
#             elif getattr(obj, "__test__", True):
#                 if isgeneratorfunction(obj):
#                     filename, lineno = compat_getfslineno(obj)
#                     warn_explicit(
#                         message=PytestCasesCollectionWarning(
#                             "cannot collect %r because it is a generator function." % name
#                         ),
#                         category=None,
#                         filename=str(filename),
#                         lineno=lineno + 1,
#                     )
#                 else:
#                     res = list(self._gencases(name, obj))
#                 outcome.force_result(res)
#
#     def iscasefunction(self, obj, name):
#         """Similar to PyCollector.istestfunction"""
#         if name.startswith("case_"):
#             if isinstance(obj, staticmethod):
#                 # static methods need to be unwrapped
#                 obj = getattr(obj, "__func__", False)
#             return (
#                 getattr(obj, "__call__", False)
#                 and not is_fixture(obj) is None
#             )
#         else:
#             return False
#
#     def iscaseclass(self, obj, name):
#         """Similar to PyCollector.istestclass"""
#         return name.startswith("Case")
#
#     def _gencases(self, name, funcobj):
#         # generate the case associated with a case function object.
#         # note: the original PyCollector._genfunctions has a "metafunc" mechanism here, we do not need it.
#         return []
#
#

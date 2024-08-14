#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Copyright 2020-2022 F4PGA Authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# SPDX-License-Identifier: Apache-2.0

from pathlib import Path
import os
from functools import cmp_to_key

from v2x import vlog_to_model
from v2x import vlog_to_pbtype
from v2x.xmlinc import xmlinc
from v2x.mux_gen import mux_gen

from vtr_xml_utils import convert

from shutil import copytree

TEST_TMP_SUFFIX = 'build/'


def prepare_files():
    """Prepares the files for running tests.

    It copies all test files to the temporary build/ directory.
    It also generates files that are required by the test files as XInclude and
    are not part of any test.
    """
    # Copy all files for tests to the build/ directory
    scriptdir = os.path.dirname(__file__)
    testdir = os.path.join(os.path.dirname(scriptdir), TEST_TMP_SUFFIX)
    os.makedirs(testdir, exist_ok=True)

    for tdir in os.listdir(scriptdir):
        s = os.path.join(scriptdir, tdir)
        d = os.path.join(testdir, tdir)
        if os.path.isdir(s):
            copytree(s, d, dirs_exist_ok=True)

    # Generate muxes/routing for tests/muxes model
    mux_gen(outdir=os.path.join(testdir, 'muxes/routing'),
            outfilename='rmux',
            datatype='routing',
            width=2,
            split_inputs=True,
            name_output='O',
            name_mux='RMUX',
            name_inputs='I0,I1'
            )
    # Generate dff.pb_type.xml required by various tests
    newpbfile = os.path.join(testdir, 'vtr/dff/dff.pb_type.xml')
    pbtypeout = vlog_to_pbtype.vlog_to_pbtype(
        [os.path.join(testdir, 'vtr/dff/dff.sim.v')],
        newpbfile,
        None)
    with open(newpbfile, 'w') as model:
        model.write(pbtypeout)

    # Generate dff.pb_type.xml required by various tests
    newpbfile = os.path.join(testdir, 'vtr/lutff-pair/dff/dff.pb_type.xml')
    pbtypeout = vlog_to_pbtype.vlog_to_pbtype(
        [os.path.join(testdir, 'vtr/lutff-pair/dff/dff.sim.v')],
        newpbfile,
        'DFF')
    with open(newpbfile, 'w') as model:
        model.write(pbtypeout)


def order_based_on_deps(left, right):
    """Compares two Verilog files  based on their dependencies.

    It checks if any of two files depends on the other and and applies an
    order in which the Verilog file required by the other is processed first
    during tests. If both files do not depend on each other, they are ordered
    by their number of dependencies.

    Parameters
    ----------
    left: str
        The left operand in the comparison, which is a path to Verilog file.
    right: str
        The right operand in the comparison, which is a path to Verilog file.
    """
    # TODO: this is overly simplified sorting over files with dependencies
    # normally it should be solved with use of topological sort
    with open(left, 'r') as leftfile:
        relhref = xmlinc.make_relhref(left, right)
        leftcontent = leftfile.read()
        if relhref in leftcontent:
            return 1
        leftinccount = leftcontent.count('`include')
    with open(right, 'r') as rightfile:
        relhref = xmlinc.make_relhref(right, left)
        rightcontent = rightfile.read()
        if relhref in rightcontent:
            return -1
        rightinccount = rightcontent.count('`include')
    return leftinccount - rightinccount


def find_files(pattern, rootdir):
    """Finds files that match pattern in the given directory.

    Parameters
    ----------
    pattern: str
        A regex pattern for files in the rootdir.
    rootdir: str
        A directory in which the function should look for files.
    """
    return [str(f) for f in Path(os.path.abspath(rootdir)).glob(pattern)]


def get_test_goldens(goldentype, testfile):
    """Gets all files for testing that match a goldentype regex.

    Parameters
    ----------
    goldentype: str
        A suffix for golden* files that should be used for tests.
    testfile: str
        A path to test script.
    """
    simfiles = sorted(
        sorted(convert.get_filenames_containing('*.sim.v', testfile)),
        key=cmp_to_key(order_based_on_deps))
    goldens = []
    for sim in simfiles:
        res = find_files('golden.' + goldentype, os.path.dirname(sim))
        if len(res) == 1:
            goldens.append({
                'simfile': sim,
                'goldenfile': res[0]})
    return goldens


def pytest_generate_tests(metafunc):
    """Scans for golden files and applies appropriate tests for those files.

    Parameters
    ----------
    metafunc: A pytest object representing the test context.
    """
    prepare_files()
    scriptdir = os.path.dirname(__file__)
    testdir = os.path.join(os.path.dirname(scriptdir), TEST_TMP_SUFFIX)

    if "modelcase" in metafunc.fixturenames:
        models = get_test_goldens('model.xml', os.path.join(testdir, 'test'))
        metafunc.parametrize("modelcase",
                             models,
                             ids=[i['simfile'] for i in models])
    if "pbtypecase" in metafunc.fixturenames:
        models = get_test_goldens('pb_type.xml', os.path.join(testdir, 'test'))
        metafunc.parametrize("pbtypecase",
                             models,
                             ids=[i['simfile'] for i in models])


def test_model_generation_with_vlog_to_model(modelcase):
    """Checks  model.xml files produced by the vlog_to_model.

    Parameters
    ----------
    modelcase : dict
        A dict of the filename of the model.xml file that should be produced
        by the corresponding sim.v file ('goldenfile') and the corresponding
        sim.v file ('simfile')
    """
    modelfile = modelcase['goldenfile']
    testdatadir = os.path.dirname(modelfile) + '/'
    vlog_filename = modelcase['simfile']
    testname = vlog_filename.split('/')[-1].split('.')[0]
    generatedmodelfile = os.path.join(testdatadir, testname) + '.model.xml'
    modelout = vlog_to_model.vlog_to_model([vlog_filename], None, None,
                                           generatedmodelfile)
    with open(generatedmodelfile, 'w') as model:
        model.write(modelout)

    convertedgolden = convert.vtr_stylize_xml(modelfile)
    convertedmodel = convert.vtr_stylize_xml(generatedmodelfile)

    with open(generatedmodelfile + '.actual', 'w') as model:
        model.write(convertedmodel)

    assert convertedmodel == convertedgolden


def test_pbtype_generation_with_vlog_to_pbtype(pbtypecase):
    """Checks  pb_type.xml files produced by the vlog_to_pbtype.

    Parameters
    ----------
    pbtypecase : dict
        A dict of the filename of the model.xml file that should be produced
        by the corresponding sim.v file ('goldenfile') and the corresponding
        sim.v file ('simfile')
    """
    testdatafile = pbtypecase['goldenfile']
    testdatadir = os.path.dirname(testdatafile) + '/'
    vlog_filename = pbtypecase['simfile']
    testname = vlog_filename.split('/')[-1].split('.')[0]
    generatedmodelfile = os.path.join(testdatadir, testname) + '.pb_type.xml'
    pbtypeout = vlog_to_pbtype.vlog_to_pbtype([vlog_filename],
                                              generatedmodelfile,
                                              None)
    with open(generatedmodelfile, 'w') as model:
        model.write(pbtypeout)

    convertedgolden = convert.vtr_stylize_xml(testdatafile)
    convertedmodel = convert.vtr_stylize_xml(generatedmodelfile)

    with open(generatedmodelfile + '.actual', 'w') as model:
        model.write(convertedmodel)

    assert convertedmodel == convertedgolden

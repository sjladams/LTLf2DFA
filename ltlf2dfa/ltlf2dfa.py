#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# This file is part of ltlf2dfa.
#
# ltlf2dfa is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# ltlf2dfa is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with ltlf2dfa.  If not, see <https://www.gnu.org/licenses/>.
#

"""Main module of the pakage."""

import itertools as it
import os
import re
import signal
# from subprocess import PIPE, Popen, TimeoutExpired  # nosec B404
import subprocess

from sympy import And, Not, Or, simplify, symbols

from ltlf2dfa.base import MonaProgram
from ltlf2dfa.helpers import check_

PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))

UNSAT_DOT = """digraph MONA_DFA {
 rankdir = LR;
 center = true;
 size = "7.5,10.5";
 edge [fontname = Courier];
 node [height = .5, width = .5];
 node [shape = doublecircle];
 node [shape = circle]; 1;
 init [shape = plaintext, label = ""];
 init -> 1;
 1 -> 1 [label="true"];
}"""


def get_value(text, regex, value_type=float):
    """Dump a value from a file based on a regex passed in."""
    pattern = re.compile(regex, re.MULTILINE)
    results = pattern.search(text)
    if results:
        return value_type(results.group(1))
    print(f"Could not find the value {regex}, in the text provided")
    return value_type(0.0)


def ter2symb(ap, ternary):
    """Translate ternary output to symbolic."""
    expr = And()
    i = 0
    for value in ternary:
        if value == "1":
            expr = And(expr, ap[i] if isinstance(ap, tuple) else ap)
        elif value == "0":
            check_(value == "0")
            expr = And(expr, Not(ap[i] if isinstance(ap, tuple) else ap))
        else:
            check_(value == "X", "[ERROR]: the guard is not X")
        i += 1
    return expr


def simplify_guard(guards):
    """Make a big OR among guards and simplify them."""
    return simplify(Or(*guards))


def parse_mona(mona_output):
    """Parse mona output and construct a dot."""
    free_variables = get_value(
        mona_output, r".*DFA for formula with free variables:[\s]*(.*?)\n.*", str
    )
    if "state" in free_variables:
        free_variables = None
    else:
        free_variables = symbols(
            " ".join(
                x.strip().lower() for x in free_variables.split() if len(x.strip()) > 0
            )
        )

    # initial_state = get_value(mona_output, '.*Initial state:[\s]*(\d+)\n.*', int)
    accepting_states = get_value(mona_output, r".*Accepting states:[\s]*(.*?)\n.*", str)
    accepting_states = [
        str(x.strip()) for x in accepting_states.split() if len(x.strip()) > 0
    ]
    # num_states = get_value(mona_output, '.*Automaton has[\s]*(\d+)[\s]states.*', int) - 1

    dot = """digraph MONA_DFA {
 rankdir = LR;
 center = true;
 size = "7.5,10.5";
 edge [fontname = Courier];
 node [height = .5, width = .5];\n"""
    dot += f" node [shape = doublecircle]; {'; '.join(accepting_states)};\n"
    dot += """ node [shape = circle]; 1;
 init [shape = plaintext, label = ""];
 init -> 1;\n"""

    dot_trans = {}  # maps each couple (src, dst) to a list of guards
    for line in mona_output.splitlines():
        if line.startswith("State "):
            orig_state = get_value(line, r".*State[\s]*(\d+):\s.*", int)
            guard = get_value(line, r".*:[\s](.*?)[\s]->.*", str)
            if free_variables:
                guard = ter2symb(free_variables, guard)
            else:
                guard = ter2symb(free_variables, "X")
            dest_state = get_value(line, r".*state[\s]*(\d+)[\s]*.*", int)
            if orig_state:
                if (orig_state, dest_state) in dot_trans:
                    dot_trans[(orig_state, dest_state)].append(guard)
                else:
                    dot_trans[(orig_state, dest_state)] = [guard]

    for c, guards in dot_trans.items():
        simplified_guard = simplify_guard(guards)
        dot += f' {c[0]} -> {c[1]} [label="{str(simplified_guard).lower()}"];\n'

    dot += "}"
    return dot


def compute_declare_assumption(s):
    """Compute declare assumptions."""
    pairs = list(it.combinations(s, 2))

    if pairs:
        first_assumption = "~(ex1 y: 0<=y & y<=max($) & ~("
        for symbol in s:
            if symbol == s[-1]:
                first_assumption += "y in " + symbol + "))"
            else:
                first_assumption += "y in " + symbol + " | "

        second_assumption = "~(ex1 y: 0<=y & y<=max($) & ~("
        for pair in pairs:
            if pair == pairs[-1]:
                second_assumption += f"(y notin {pair[0]} | y notin {pair[1]})));"
            else:
                second_assumption += f"(y notin {pair[0]} | y notin {pair[1]}) & "

        return first_assumption + " & " + second_assumption
    return None


def createMonafile(p: str):
    """Write the .mona file."""
    try:
        with open(f"{PACKAGE_DIR}/automa.mona", "w+", encoding="utf-8") as file:
            file.write(p)
    except IOError:
        print("[ERROR]: Problem opening the automa.mona file!")


def invoke_mona():
    """Execute the MONA tool."""
    command = f"mona -q -u -w {PACKAGE_DIR}/automa.mona"
    try:
        completed_proc = subprocess.run(
            command,
            shell=True,
            timeout=30,
            capture_output=True,  # Fixed typo here
            encoding="utf-8")
        return str(completed_proc.stdout).strip()
    except subprocess.TimeoutExpired:  # Correctly catching the TimeoutExpired exception
        print("The command timed out.")  # Optionally log the timeout
        return False
    except Exception as e:  # Optionally catch other exceptions
        print(f"An error occurred: {e}")
        return False


def output2dot(mona_output):
    """Parse the mona output or return the unsatisfiable dot."""
    if "Formula is unsatisfiable" in mona_output:
        return UNSAT_DOT
    return parse_mona(mona_output)


def to_dfa(f, mona_dfa_out=False) -> str:
    """Translate to deterministic finite-state automaton."""
    p = MonaProgram(f)
    mona_p_string = p.mona_program()
    createMonafile(mona_p_string)
    mona_dfa = invoke_mona()
    if mona_dfa_out:
        return mona_dfa
    check_(mona_dfa_out is False)
    return output2dot(mona_dfa)

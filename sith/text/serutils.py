# Sith Blender Addon
# Copyright (C) 2019-2026 Crt Vavros
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

from typing import TextIO, Union

kMaxNameLen = 64


def isValidNameLen(name: str):
    return len(name) <= kMaxNameLen


def isASCII(name: str):
    return all(ord(char) < 128 for char in name)


def assertName(name: str, *, allowSpaces: bool = False, maxLength=kMaxNameLen):
    if not name or any(ord(char) < 32 or ord(char) == 127 or char in '\"#' for char in name):
        raise AssertionError('Names must be nonempty and contain no control characters, quotes or #')
    if not allowSpaces and ' ' in name:
        raise AssertionError('Unquoted identifier tokens cannot contain whitespace')
    if maxLength is not None and len(name) > maxLength:
        raise AssertionError(f"name error: len of '{name}' is greater then {maxLength} chars")
    if not isASCII(name):
        raise AssertionError(f"name error: '{name}' does not contain all ASCII chars")


def makeComment(comment: str):
    if not comment:
        return ''
    # Header comments may contain caller text or filenames. Every physical
    # line must stay a comment, never an extra resource section or field.
    lines = comment.replace('\r\n', '\n').replace('\r', '\n').split('\n')
    return '\n'.join('# ' + line for line in lines)

def writeNewLine(file: TextIO):
    file.write("\n")

def writeLine(file: TextIO, line: str):
    file.write(line)
    writeNewLine(file)

def writeCommentLine(file: TextIO, comment: str):
    cline = makeComment(comment)
    if len(cline) > 0:
        writeLine(file, cline)

def writeKeyValue(file: TextIO, key: str, value: Union[str, int], width: int = 0):
    line = key.upper().ljust(width) + " " + str(value)
    writeLine(file, line)

def writeSectionTitle(file: TextIO, section: str):
    writeLine(file, "###############")
    writeLine(file, "SECTION: " + section.upper())
    writeNewLine(file)

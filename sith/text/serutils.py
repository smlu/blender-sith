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

def makeComment(comment: str):
    cline = ""
    if len(comment) > 0:
        cline = '# ' + comment
    return cline

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

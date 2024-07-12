# Sith Blender Addon
# Copyright (c) 2019-2024 Crt Vavros

# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:

# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.

# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

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

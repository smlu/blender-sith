# Sith Blender Addon
# Copyright (c) 2019-2022 Crt Vavros

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

def makeComment(comment):
    cline = ""
    if len(comment) > 0:
        cline = '# ' + comment
    return cline

def writeNewLine(file):
    file.write("\n")

def writeLine(file, line):
    file.write(line)
    writeNewLine(file)

def writeCommentLine(file, comment):
    cline = makeComment(comment)
    if len(cline) > 0:
        writeLine(file, cline)

def writeKeyValue(file, key: str, value, width = 0):
    line = key.upper().ljust(width) + " " + str(value)
    writeLine(file, line)

def writeSectionTitle(file, section):
    writeLine(file, "###############")
    writeLine(file, "SECTION: " + section.upper())
    writeNewLine(file)

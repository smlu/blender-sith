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

from enum import Enum
from typing import Callable, Tuple, TextIO
from ..types.vector import *

class TokenType(Enum):
    Invalid    = 1
    EOF        = 2
    EOL        = 3
    Identifier = 4
    HexInteger = 5
    Integer    = 6
    Float      = 7
    String     = 8
    Punctuator = 9

class Token:
    def __init__(self, t: TokenType = TokenType.Invalid):
        self.t = t
        self.v = ""

        self.file_name    = ""
        self.begin_line   = 0
        self.begin_column = 0
        self.end_line     = 0
        self.end_column   = 0

    @property
    def type(self) -> TokenType:
        return self.t

    @type.setter
    def type(self, t: TokenType):
        self.t = t

    def setType(self, t: TokenType):
        self.t = t

    @property
    def value(self) -> str:
        return self.v

    @value.setter
    def value(self, v: str):
        self.v = v

    def setValue(self, v: str):
        self.v = v

    @property
    def filename(self) -> str:
        return self.file_name

    @filename.setter
    def filename(self, name: str):
        self.file_name = name

    def setFileName(self, name: str):
        self.file_name = name

    @property
    def beginLine(self) -> int:
        return self.begin_line

    @beginLine.setter
    def beginLine(self, line: int):
        self.begin_line = line

    def setBeginLine(self, line: int):
        self.begin_line = line

    @property
    def beginColumn(self) -> int:
        return self.begin_column

    @beginColumn.setter
    def beginColumn(self, column: int):
        self.begin_column = column

    def setBeginColumn(self, column: int):
        self.begin_column = column

    @property
    def endLine(self) -> int:
        return self.end_line

    @endLine.setter
    def endLine(self, line: int):
        self.end_line = line

    def setEndLine(self, line: int):
        self.end_line = line

    @property
    def endColumn(self) -> int:
        return self.end_column

    @endColumn.setter
    def endColumn(self, column: int):
        self.end_column = column

    def setEndColumn(self, column: int):
        self.end_column = column

    def toIntNumber(self) -> int:
        if self.type != TokenType.Integer and self.type != TokenType.HexInteger:
            raise TypeError("Token type is not integer number")

        base = 10 if self.type == TokenType.Integer else 16
        return int(self.value, base)

    def toFloatNumber(self) -> float:
        if self.type != TokenType.Float and self.type != TokenType.Integer:
            raise TypeError("Token type is not float number")
        return float(self.value)

def _ctoi(c: str) -> int:
    if type(c) == type(""):
        return ord(c)
    else:
        return -1

def isupper(c: str): return 65 <= _ctoi(c) <= 90
def islower(c: str): return 97 <= _ctoi(c) <= 122
def isdigit(c: str): return 48 <= _ctoi(c) <= 57
def isalpha(c: str): return isupper(c) or islower(c)
def isalnum(c: str): return isalpha(c) or isdigit(c)
def isgraph(c: str): return 33 <= _ctoi(c) <= 126
def ispunct(c: str): return isgraph(c) and not isalnum(c)
def isxdigit(c: str): return isdigit(c) or \
    (65 <= _ctoi(c) <= 70) or (97 <= _ctoi(c) <= 102)

class Tokenizer:
    def __init__(self, file: TextIO):
        self.f          = file
        self.report_eol = False
        self.line       = 1
        self.column     = 1

        self.current_ch = self._read_ch()
        self.next_ch    = self._read_ch()


    def getToken(self) -> Token:
        self._skip_whitespace()

        t = Token()
        t.beginLine   = self.line
        t.beginColumn = self.column

        if self.current_ch == '':
            t.type = TokenType.EOF

        elif self.current_ch == '\n':
            t.type = TokenType.EOL
            self._read_next()

        elif self.current_ch  == '\"':
            t = self._read_string(t)

        elif self._is_identifier_prefix(self.current_ch):
            t = self._read_identifier(t)

        elif self.current_ch.isdigit():
            t = self._read_numeric_literal(t)

        elif ispunct(self.current_ch):
            if self.current_ch == '.' and self.next_ch.isdigit():
                t = self._read_numeric_literal(t)
            elif self.current_ch == '-' and (self.next_ch == '.' or self.next_ch.isdigit()):
                t = self._read_numeric_literal(t)
            elif self.current_ch == '-' and self.next_ch.isdigit():
                t = self._read_numeric_literal(t)
            else:
                t.type = TokenType.Punctuator
                t.value += self.current_ch
                self._read_next()
        else:
            t.type = TokenType.Invalid

        t.endLine   = self.line
        t.endColumn = self.column
        return t

    def getDelimitedStringToken(self, isDelim: Callable[[str], bool]) -> Token:
        self._skip_whitespace()

        t = Token()
        t.beginLine = self.line
        t.beginColumn = self.column

        while not isDelim(self.current_ch) and self.current_ch != '':
            t.value += self.current_ch
            self._read_next()

        t.type = TokenType.String
        t.endLine = self.line
        t.endColumn = self.column
        return t

    def getIdentifier(self) -> str:
        t = self.getToken()
        if t.type != TokenType.Identifier:
            IOError(f'Expected identifier! line: {self.line} column: {self.column}')
        return t.value

    def getString(self) -> str:
        t = self.getToken()
        if t.type != TokenType.String:
            IOError(f'Expected string! line: {self.line} column: {self.column}')
        return t.value

    def getSpaceDelimitedString(self) -> str:
        t = self.getDelimitedStringToken(lambda x: x.isspace())
        if not t.value or len(t.value) == 0:
            IOError(f'Expected string got null! line: {self.line} column: {self.column}')
        return t.value

    def getIntNumber(self) -> int:
        t = self.getToken()
        return t.toIntNumber()

    def getFloatNumber(self) -> float:
        t = self.getToken()
        return t.toFloatNumber()


    def getPairOfInts(self) -> Tuple[int, int]:
        x = self.getIntNumber()
        self.assertPunctuator(',')
        y = self.getIntNumber()
        return (x,y)

    def getVector2f(self) -> Vector2f:
        x = self.getFloatNumber()
        y = self.getFloatNumber()
        return Vector2f(x,y)

    def getVector3f(self) -> Vector3f:
        x = self.getFloatNumber()
        y = self.getFloatNumber()
        z = self.getFloatNumber()
        return Vector3f(x,y,z)

    def getVector4f(self) -> Vector4f:
        t = self.getToken()
        vecSimple = t.type == TokenType.Float

        if vecSimple:
            x = t.toFloatNumber()
        else:
            x = self.getFloatNumber()
            self.assertPunctuator('/')

        y = self.getFloatNumber()
        if not vecSimple:
            self.assertPunctuator('/')

        z = self.getFloatNumber()
        if not vecSimple:
            self.assertPunctuator('/')

        w = self.getFloatNumber()
        if not vecSimple:
            self.assertPunctuator(')')

        return Vector4f(x,y,z,w)

    def assertIdentifier(self, id: str):
        t = self.getToken()
        if t.type != TokenType.Identifier or t.value.lower() != id.lower():
            raise AssertionError(f"Expected identifier '{id}', found '{t.value}'! line: {self.line} column: {self.column}")

    def assertInteger(self, num: int):
        t = self.getToken()
        if t.type != TokenType.Integer or t.toIntNumber() != num:
            raise AssertionError(f"Expected integer '{num}', found '{t.toIntNumber()}'! line: {self.line} column: {self.column}")

    def assertPunctuator(self, punc: str):
        t = self.getToken()
        if t.type != TokenType.Punctuator or t.value.lower() != punc.lower():
            raise AssertionError(f"Expected punctuator '{punc}', found '{t.value}'! line: {self.line} column: {self.column}")

    def assertLabel(self, label: str):
        self.assertIdentifier(label)
        self.assertPunctuator(':')

    def assertEndOfFile(self):
        t = self.getToken()
        if t.type != TokenType.EOF :
            raise AssertionError(f'Expected end of file! line: {self.line} column: {self.column}')

    def _read_ch(self) -> str:
        c = self.f.read(1)
        if not c:
            return ''
        return c

    def _read_next(self):
        self.column += 1

        if(self.current_ch == '\n'):
            self.line += 1
            self.column = 1

        self.current_ch = self.next_ch
        self.next_ch = self._read_ch()

    def _skip_whitespace_step(self) -> bool:
        if self.current_ch == '': # EOF
            return False
        elif self.report_eol and self.current_ch == '\n': # EOL
            return False
        elif self.current_ch.isspace():
            self._read_next()
            return True
        elif self.current_ch == '#': # Comment
            self._skip_to_next_line()
            return True
        return False

    def _skip_whitespace(self):
        if self._skip_whitespace_step():
            self._skip_whitespace()

    def _skip_to_next_line(self):
        while self.current_ch != '\n' and self.current_ch != '':
            self._read_next()

    def _is_identifier_prefix(self, c: str) -> bool:
        return c.isalpha() or c == '_'

    def _is_identifier_char(self, c: str) -> bool:
        return c.isalnum() or c == '_'

    def _read_hex_numeric_literal(self, token: Token) -> Token:
        while(isxdigit(self.current_ch)):
            token.value += self.current_ch
            self._read_next()
        return token

    def _read_integral_numeric_literal(self, token: Token) -> Token:
        while(self.current_ch.isnumeric()):
            token.value += self.current_ch
            self._read_next()
        return token

    def _read_numeric_literal(self, token: Token) -> Token:
        if self.current_ch == '-' or self.current_ch == '+':
            token.value += self.current_ch
            self._read_next()

        if self.current_ch == '0' and self.next_ch.lower() == 'x':
            token.type = TokenType.HexInteger
            token.value += self.current_ch
            token.value += self.next_ch

            self._read_next()
            self._read_next()

            token = self._read_hex_numeric_literal(token)
            return token

        token.type = TokenType.Integer
        token = self._read_integral_numeric_literal(token)

        if self.current_ch == '.' and (self.next_ch.isdigit() or self.next_ch == '#'): # checking for # fixes problems with '.#QNAN0'
            if not token.value or not token.value[-1:].isdigit():
                token.value += '0' # Prepend 0 to poorly formatted floating point number

            token.value += self.current_ch
            self._read_next()

            token = self._read_integral_numeric_literal(token)
            token.type = TokenType.Float

        if self.current_ch.lower() == 'e':
            token.value += self.current_ch
            self._read_next()

            if self.current_ch == '-' or self.current_ch == '+':
                token.value += self.current_ch
                self._read_next()

            token = self._read_integral_numeric_literal(token)
            token.type = TokenType.Float

        return token

    def _read_identifier(self, token: Token) -> Token:
        if self._is_identifier_prefix(self.current_ch):

            token.type = TokenType.Identifier
            while self._is_identifier_char(self.current_ch):
                token.value += self.current_ch
                self._read_next()
        return token

    def _read_string(self, token: Token) -> Token:
        while True:
            self._read_next()

            if self.current_ch == '':
                token.endLine   = self.line
                token.endColumn = self.column
                raise IOError(f'Unexpected end of a file! line: {self.line} column: {self.column}')

            if self.current_ch == '\n':
                token.endLine   = self.line
                token.endColumn = self.column
                raise IOError(f'Unexpected newline in string literal! line: {self.line} column: {self.column}')

            if self.current_ch == '"':
                token.type = TokenType.String
                self._read_next()
                return token

            if self.current_ch == '\\':  # Escape sequence
                self._read_next()

                if self.current_ch == '\n':
                    pass
                elif self.current_ch in ['\'', '"', '\\']:
                    token.value += self.current_ch
                elif self.current_ch == 'n':
                    token.value += '\n'
                elif self.current_ch == 't':
                    token.value += '\t'
                else:
                    token.type = TokenType.Invalid
                    return token
            else:
                token.value += self.current_ch

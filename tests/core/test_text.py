import io
import unittest

from sith.text.tokenizer import Tokenizer, TokenType
from sith.types import Vector2f, Vector3f, Vector4f
from sith.key import KeyFlag
from sith.text.serutils import makeComment, writeCommentLine


class CommentWriterTests(unittest.TestCase):
    def test_every_comment_line_is_prefixed(self):
        for newline in ('\n', '\r', '\r\n'):
            with self.subTest(newline=repr(newline)):
                text = newline.join(('Export header', '', 'SECTION: NOT_DATA', ''))
                expected = '# Export header\n# \n# SECTION: NOT_DATA\n# '
                self.assertEqual(makeComment(text), expected)
                output = io.StringIO()
                writeCommentLine(output, text)
                self.assertEqual(output.getvalue(), expected + '\n')
        self.assertEqual(makeComment(''), '')
        self.assertEqual(makeComment('Single line'), '# Single line')
        output = io.StringIO()
        writeCommentLine(output, '')
        self.assertEqual(output.getvalue(), '')

    def test_multiline_headers_cannot_be_parsed_as_resource_sections(self):
        from pathlib import Path
        import tempfile
        from fixtures import TV
        from sith.key.keyLoader import loadKey
        from sith.key.keyWriter import saveKey
        from sith.model.model3doLoader import load3do
        from sith.model.model3doWriter import save3do
        from batch.common import differences, key_snapshot, model_snapshot

        # Comment text resembling a duplicate header must remain inert after
        # both serializers write it, including CR and CRLF input from callers.
        key = loadKey(TV / 'key' / 'fractional.key')
        model, version = load3do(TV / 'model' / 'triangle.3do')
        for extension in ('key', '3do'):
            for newline in ('\n', '\r', '\r\n'):
                with self.subTest(format=extension, newline=repr(newline)), tempfile.TemporaryDirectory() as directory:
                    header = 'Export comment' + newline + 'SECTION: HEADER' + newline + 'not resource data'
                    path = Path(directory) / ('roundtrip.' + extension)
                    if extension == 'key':
                        saveKey(key, path, header)
                        self.assertEqual(differences(key_snapshot(key), key_snapshot(loadKey(path))), [])
                    else:
                        save3do(model, path, version, header)
                        self.assertEqual(differences(model_snapshot(model), model_snapshot(load3do(path)[0])), [])


class TokenizerTests(unittest.TestCase):
    def tokenizer(self, text):
        return Tokenizer(io.StringIO(text))

    def test_numbers_hex_signs_and_exponents(self):
        for text, expected in (('0', 0), ('-42', -42), ('+42', 42), ('0x2a', 42),
                               ('0X2AbF', 0x2abf), ('-0x10', -16), ('+0x10', 16)):
            with self.subTest(text=text):
                tok = self.tokenizer(text)
                self.assertEqual(tok.getIntNumber(), expected)
                tok.assertEndOfFile()
        for text, expected in (('1.25', 1.25), ('-.5', -0.5), ('2e3', 2000),
                               ('-1.5E-2', -0.015), ('.125', 0.125), ('1e+2', 100),
                               ('+1.25', 1.25), ('+.5', 0.5), ('1.', 1), ('+1.', 1),
                               ('-1.', -1), ('1.e2', 100), ('+1.e-2', 0.01), ('-0.', -0.0)):
            with self.subTest(text=text):
                tok = self.tokenizer(text)
                self.assertEqual(tok.getFloatNumber(), expected)
                tok.assertEndOfFile()

    def test_incomplete_signed_decimals_and_exponents_are_rejected(self):
        for text in ('.', '+', '-', '+.', '-.', '+.e2', '-.e2', '1e', '1e+', '1e-', '1.e'):
            with self.subTest(text=text), self.assertRaises((ValueError, TypeError)):
                self.tokenizer(text).getFloatNumber()

    def test_comments_crlf_tabs_blank_lines_and_eof(self):
        tok = self.tokenizer('# comment\r\n\t\n  section : header # tail\n')
        tok.assertLabel('SECTION')
        tok.assertIdentifier('HEADER')
        tok.assertEndOfFile()
        tok.assertEndOfFile()

    def test_large_whitespace_run(self):
        self.tokenizer(' ' * 4096 + 'value').assertIdentifier('value')

    def test_vectors_pairs_and_both_rgba_forms(self):
        self.assertEqual(self.tokenizer('1 2').getVector2f(), Vector2f(1, 2))
        self.assertEqual(self.tokenizer('1 2 3').getVector3f(), Vector3f(1, 2, 3))
        for text in ('1.0 2.0 3.0 4.0', '1 2 3 4', '(1/2/3/4)'):
            self.assertEqual(self.tokenizer(text).getVector4f(), Vector4f(1, 2, 3, 4))
        self.assertEqual(self.tokenizer('-1, 2').getPairOfInts(), (-1, 2))

    def test_malformed_vectors_are_rejected(self):
        for text in ('[1/2/3/4)', '(1,2,3,4)', '(1/2/3)', '1 2'):
            with self.subTest(text=text), self.assertRaises((AssertionError, TypeError)):
                self.tokenizer(text).getVector4f()

    def test_quoted_strings_and_escapes(self):
        self.assertEqual(self.tokenizer(r'"a b\n\t\"\\"').getString(), 'a b\n\t"\\')
        for text in ('"unfinished', '"line\nbreak"'):
            with self.subTest(text=text), self.assertRaises(OSError):
                self.tokenizer(text).getString()

    def test_wrong_token_types_are_rejected(self):
        for method, text in (('getIdentifier', '123'), ('getString', '123'),
                             ('getSpaceDelimitedString', ''), ('getIntNumber', 'abc'),
                             ('getFloatNumber', 'abc')):
            with self.subTest(method=method), self.assertRaises((OSError, TypeError)):
                getattr(self.tokenizer(text), method)()

    def test_assertions_reject_wrong_values(self):
        for method, args in (('assertIdentifier', ('other',)), ('assertInteger', (2,)),
                             ('assertPunctuator', (':',)), ('assertEndOfFile', ())):
            with self.subTest(method=method), self.assertRaises((AssertionError, TypeError)):
                getattr(self.tokenizer('1'), method)(*args)

    def test_token_source_positions_and_eol(self):
        tok = self.tokenizer('first\n  second')
        tok.report_eol = True
        first = tok.getToken()
        self.assertEqual((first.type, first.beginLine, first.beginColumn), (TokenType.Identifier, 1, 1))
        self.assertEqual(tok.getToken().type, TokenType.EOL)
        second = tok.getToken()
        self.assertEqual((second.beginLine, second.beginColumn, second.value), (2, 3, 'second'))


class DataTypeTests(unittest.TestCase):
    def test_flag_hex_and_set_round_trips(self):
        for flag in (KeyFlag(0), *KeyFlag, KeyFlag(0x7f)):
            self.assertEqual(KeyFlag.fromHex(flag.hex()), flag)
            self.assertEqual(KeyFlag.fromSet(flag.toSet()), flag)
        self.assertEqual(KeyFlag.fromHex(''), KeyFlag(0))
        self.assertEqual(KeyFlag.fromSet({'NoLoop', 'unknown'}), KeyFlag.NoLoop)

    def test_vector_components_and_immutability(self):
        for vector in (Vector2f(1, 2), Vector3f(1, 2, 3), Vector4f(1, 2, 3, 4)):
            self.assertEqual(vector.x, 1)
            self.assertEqual(vector.y, 2)
            with self.assertRaises(AttributeError):
                vector.x = 9

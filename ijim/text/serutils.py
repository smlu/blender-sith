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

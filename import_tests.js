#!/usr/bin/env node

const fs = require('fs')
const path = require('path')

const DEFAULT_TIMESTAMP = '1970-01-01T00:00:00.000Z'

function parseArgs(argv) {
  const [inputDirArg, outputFileArg] = argv
  const repoRoot = __dirname

  return {
    inputDir: path.resolve(
      repoRoot,
      inputDirArg || '../canboatjs/test/pgns'
    ),
    outputFile: path.resolve(
      repoRoot,
      outputFileArg || 'tests/canboatjs_roundtrip.json'
    ),
    canboatDistDir: path.resolve(repoRoot, '../canboatjs/dist')
  }
}

function requireCanboat(canboatDistDir) {
  const fromPgnPath = path.join(canboatDistDir, 'fromPgn.js')
  const toPgnPath = path.join(canboatDistDir, 'toPgn.js')
  const stringMsgPath = path.join(canboatDistDir, 'stringMsg.js')

  if (
    !fs.existsSync(fromPgnPath) ||
    !fs.existsSync(toPgnPath) ||
    !fs.existsSync(stringMsgPath)
  ) {
    throw new Error(
      `Missing canboatjs build output in ${canboatDistDir}. Run 'npm install' and 'npm run build' in ../canboatjs first.`
    )
  }

  return {
    FromPgn: require(fromPgnPath).Parser,
    toPgn: require(toPgnPath).toPgn,
    encodeActisense: require(stringMsgPath).encodeActisense
  }
}

function listFixtureFiles(inputDir) {
  return fs
    .readdirSync(inputDir)
    .filter((fileName) => fileName.endsWith('.js'))
    .sort((left, right) => left.localeCompare(right, 'en', { numeric: true }))
}

function deepClone(value) {
  return JSON.parse(JSON.stringify(value))
}

function stripUndefined(value) {
  if (Array.isArray(value)) {
    return value.map(stripUndefined)
  }

  if (value && typeof value === 'object') {
    return Object.fromEntries(
      Object.entries(value)
        .filter(([, entryValue]) => entryValue !== undefined)
        .map(([key, entryValue]) => [key, stripUndefined(entryValue)])
    )
  }

  return value
}

function normalizeTimestamp(fixture, decodedPgn) {
  if (fixture.expected && typeof fixture.expected.timestamp === 'string') {
    return fixture.expected.timestamp
  }

  if (typeof fixture.timestamp === 'string') {
    return fixture.timestamp
  }

  if (
    typeof decodedPgn.timestamp === 'string' &&
    decodedPgn.timestamp !== '' &&
    fixture.expected &&
    Object.prototype.hasOwnProperty.call(fixture.expected, 'timestamp')
  ) {
    return decodedPgn.timestamp
  }

  return DEFAULT_TIMESTAMP
}

function sanitizeExpected(decodedPgn, timestamp) {
  const normalized = deepClone(decodedPgn)

  delete normalized.input
  delete normalized.bus
  delete normalized.canId
  delete normalized.time
  delete normalized.timer
  delete normalized.direction
  delete normalized.rawData
  delete normalized.byteMapping

  normalized.timestamp = timestamp

  return stripUndefined(normalized)
}

function decodeFixtureCase(FromPgn, fixture) {
  const parser = new FromPgn({
    format: fixture.format !== undefined ? fixture.format : 1,
    returnNulls: true,
    useCamel: true
  })

  let warningMessage
  let errorMessage

  parser.on('warning', (pgn, warning) => {
    warningMessage = `PGN ${pgn && pgn.pgn !== undefined ? pgn.pgn : 'unknown'}: ${warning}`
  })

  parser.on('error', (pgn, error) => {
    const prefix = pgn && pgn.pgn !== undefined ? `PGN ${pgn.pgn}: ` : ''
    errorMessage = `${prefix}${error instanceof Error ? error.message : String(error)}`
  })

  const inputMessages = Array.isArray(fixture.input)
    ? fixture.input
    : [fixture.input]

  let decodedPgn
  for (const message of inputMessages) {
    const result = parser.parseString(message)
    if (result) {
      if (decodedPgn) {
        throw new Error('Fixture produced multiple decoded PGNs')
      }
      decodedPgn = result
    }
  }

  if (warningMessage) {
    throw new Error(warningMessage)
  }

  if (errorMessage) {
    throw new Error(errorMessage)
  }

  if (!decodedPgn) {
    throw new Error('Fixture did not produce a decoded PGN')
  }

  return decodedPgn
}

function encodeBasicString(toPgn, encodeActisense, decodedPgn, timestamp) {
  const payload = toPgn(decodedPgn)

  return encodeActisense({
    pgn: decodedPgn.pgn,
    data: payload,
    timestamp,
    prio: decodedPgn.prio,
    dst: decodedPgn.dst,
    src: decodedPgn.src
  })
}

function decodeNormalizedInput(FromPgn, normalizedInput) {
  const parser = new FromPgn({
    format: 1,
    returnNulls: true,
    useCamel: true
  })

  const roundtrip = parser.parseString(normalizedInput)
  if (!roundtrip) {
    throw new Error('Normalized input did not decode')
  }

  return roundtrip
}

function convertFixtures({ inputDir, outputFile, canboatDistDir }) {
  const { FromPgn, toPgn, encodeActisense } = requireCanboat(canboatDistDir)
  const fixtureFiles = listFixtureFiles(inputDir)
  const cases = []

  for (const fileName of fixtureFiles) {
    const fixturePath = path.join(inputDir, fileName)
    delete require.cache[require.resolve(fixturePath)]
    const fixtureCases = require(fixturePath)

    if (!Array.isArray(fixtureCases)) {
      throw new Error(`${fileName} does not export an array`)
    }

    fixtureCases.forEach((fixture, caseIndex) => {
      const decodedPgn = decodeFixtureCase(FromPgn, fixture)
      const timestamp = normalizeTimestamp(fixture, decodedPgn)
      const input = encodeBasicString(toPgn, encodeActisense, decodedPgn, timestamp)
      const normalizedDecodedPgn = decodeNormalizedInput(FromPgn, input)
      const expected = sanitizeExpected(normalizedDecodedPgn, timestamp)
      const format = fixture.format !== undefined ? fixture.format : 1

      cases.push({
        pgn: Number(path.basename(fileName, '.js')),
        sourceFile: fileName,
        caseIndex,
        input,
        expected,
        originalInput: deepClone(fixture.input),
        originalFormat: format
      })
    })
  }

  const output = {
    generatedAt: new Date().toISOString(),
    sourceDirectory: inputDir,
    caseCount: cases.length,
    cases
  }

  fs.mkdirSync(path.dirname(outputFile), { recursive: true })
  fs.writeFileSync(outputFile, JSON.stringify(output, null, 2) + '\n', 'utf8')

  return output
}

function main() {
  try {
    const options = parseArgs(process.argv.slice(2))
    const output = convertFixtures(options)
    console.log(
      `Wrote ${output.caseCount} normalized test cases to ${options.outputFile}`
    )
  } catch (error) {
    console.error(error instanceof Error ? error.message : String(error))
    process.exitCode = 1
  }
}

main()
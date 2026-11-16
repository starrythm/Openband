import file from '@system.file'
import {blockBytes, size} from './resource-size.js'

const alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/'
const values = new Uint8Array(128)
for (let index = 0; index < alphabet.length; index++) {
  values[alphabet.charCodeAt(index)] = index
}

const blocks = new Map()

function load(index) {
  if (blocks.has(index)) {
    const previous = blocks.get(index)
    blocks.delete(index)
    blocks.set(index, previous)
    return previous
  }

  const request = new Promise((resolve, reject) => {
    file.readText({
      uri: '/common/media/part-' + index + '.txt',
      success(data) {
        const length = Math.min(blockBytes, size - index * blockBytes)
        if (data && typeof data.text === 'string' && data.text.length === Math.ceil(length / 3) * 4) resolve(data.text)
        else reject(new Error('视频分段长度有误 ' + index))
      },
      fail(data, code) { reject(new Error('读取视频段 ' + index + ' 失败 ' + code)) }
    })
  })
  blocks.set(index, request)
  if (blocks.size > 2) blocks.delete(blocks.keys().next().value)
  request.catch(() => {
    if (blocks.get(index) === request) blocks.delete(index)
  })
  return request
}

function decodeInto(text, output, written, from, count) {
  let position = Math.floor(from / 3) * 4
  let shift = (2 - from % 3) * 8
  const end = written + count
  while (written < end) {
    const word = (values[text.charCodeAt(position)] << 18)
      | (values[text.charCodeAt(position+1)] << 12)
      | (values[text.charCodeAt(position+2)] << 6)
      | values[text.charCodeAt(position+3)]
    for (; shift >= 0 && written < end; shift -= 8) output[written++] = word >> shift
    position += 4
    shift = 16
  }
}

export async function readClip(position, length) {
  if (!Number.isInteger(position) || !Number.isInteger(length) ||
      position < 0 || length < 0 || position + length > size) {
    throw new Error('视频范围有误')
  }

  const bytes = new Uint8Array(length)
  let written = 0
  while (written < length) {
    const offset = position + written
    const index = Math.floor(offset / blockBytes)
    const start = offset % blockBytes
    const count = Math.min(length - written, blockBytes - start)
    decodeInto(await load(index), bytes, written, start, count)
    written += count
  }

  // Preload near the end of a block during forward playback.
  const end = position + length
  if (length > 1024 && end % blockBytes > blockBytes - 8192) {
    const next = Math.floor(end / blockBytes) + 1
    if (next * blockBytes < size) load(next).catch(() => {})
  }
  return bytes
}

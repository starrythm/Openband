export const maxAviBytes = 6 * 1024 * 1024
const maxFrameBytes = 16 * 1024
const maxFrames = 900

function view(bytes) {
  return new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength)
}

function fourCC(bytes, offset) {
  return String.fromCharCode(bytes[offset], bytes[offset + 1], bytes[offset + 2], bytes[offset + 3])
}

function riffLength(header) {
  if (header.length !== 12 || fourCC(header, 0) !== 'RIFF' || fourCC(header, 8) !== 'AVI ') {
    throw new Error('需要 AVI 文件')
  }
  const size = view(header).getUint32(4, true) + 8
  if (size <= 12 || size > maxAviBytes) throw new Error('AVI 文件超出大小限制')
  return size
}

function chunk(bytes, offset, end) {
  const size = view(bytes).getUint32(4, true)
  const start = offset + 8
  const next = start + size + (size % 2)
  if (next > end) throw new Error('AVI 数据不完整')
  return {tag: fourCC(bytes, 0), start, size, next}
}

function streamHeader(bytes) {
  for (let offset = 4; offset < bytes.length;) {
    if (bytes.length - offset < 8) throw new Error('AVI 文件头不完整')
    const field = chunk(bytes.subarray(offset, offset + 8), offset, bytes.length)
    if (field.tag === 'strh' && field.size >= 8) {
      return fourCC(bytes, field.start) === 'vids' && fourCC(bytes, field.start + 4) === 'MJPG'
    }
    offset = field.next
  }
  return false
}

function headerInfo(bytes) {
  const data = view(bytes)
  let timing
  let mjpeg = false
  for (let offset = 4; offset < bytes.length;) {
    if (bytes.length - offset < 8) throw new Error('AVI 文件头不完整')
    const field = chunk(bytes.subarray(offset, offset + 8), offset, bytes.length)
    if (field.tag === 'avih' && field.size >= 40) {
      const start = field.start
      timing = {
        interval: data.getUint32(start, true) / 1000,
        count: data.getUint32(start + 16, true),
        streams: data.getUint32(start + 24, true),
        width: data.getUint32(start + 32, true),
        height: data.getUint32(start + 36, true)
      }
    }
    if (field.tag === 'LIST' && field.size >= 4 && fourCC(bytes, field.start) === 'strl') {
      mjpeg = streamHeader(bytes.subarray(field.start, field.start + field.size))
    }
    offset = field.next
  }
  if (!mjpeg || !timing || timing.interval < 16 || timing.interval > 1000 ||
      timing.streams !== 1 || !timing.count || timing.count > maxFrames ||
      !timing.width || timing.width > 212 || !timing.height || timing.height > 520) {
    throw new Error('视频参数不匹配')
  }
  return timing
}

export function openAvi(read) {
  let end
  let timing
  let movi
  let scanned = 0

  function next(offset) {
    if (offset + 8 > end || scanned++ >= 32) throw new Error('找不到 AVI 索引')
    return read(offset, Math.min(12, end - offset)).then(bytes => {
      const field = chunk(bytes, offset, end)
      if (field.tag === 'LIST' && field.size >= 4) {
        const type = fourCC(bytes, 8)
        if (type === 'hdrl') {
          if (field.size > 8192) throw new Error('AVI 文件头超限')
          return read(field.start, field.size).then(header => {
            timing = headerInfo(header)
            return next(field.next)
          })
        }
        if (type === 'movi') movi = field
      }
      if (field.tag === 'idx1') {
        if (!movi || !timing || field.size !== timing.count * 16) throw new Error('AVI 索引有误')
        return read(field.start, field.size).then(entries => {
          const data = view(entries)
          const frames = []
          let previousEnd = movi.start + 4
          for (let n = 0; n < entries.length; n += 16) {
            const tag = fourCC(entries, n)
            const offset = movi.start + data.getUint32(n + 8, true) + 8
            const length = data.getUint32(n + 12, true)
            if ((tag !== '00dc' && tag !== '00db') || length < 4 || length > maxFrameBytes ||
                offset - 8 < previousEnd || offset + length > movi.start + movi.size) {
              throw new Error('AVI 索引有误')
            }
            frames.push({offset, length})
            previousEnd = offset + length + (length % 2)
          }
          return {frames, interval: timing.interval}
        })
      }
      return next(field.next)
    })
  }

  return read(0, 12).then(header => {
    end = riffLength(header)
    return next(12)
  })
}

export function checkFrame(bytes) {
  if (bytes[0] !== 255 || bytes[1] !== 216 ||
      bytes[bytes.length - 2] !== 255 || bytes[bytes.length - 1] !== 217) {
    throw new Error('视频帧格式有误')
  }
  return bytes
}

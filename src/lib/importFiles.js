function arrayBufferToBase64(buffer) {
  const bytes = new Uint8Array(buffer);
  const chunkSize = 0x8000;
  let binary = '';
  for (let index = 0; index < bytes.length; index += chunkSize) {
    const chunk = bytes.subarray(index, index + chunkSize);
    binary += String.fromCharCode(...chunk);
  }
  return btoa(binary);
}

export async function buildImportedFilePayloads(fileList) {
  const files = Array.from(fileList ?? []);
  const payloads = [];
  for (const file of files) {
    const buffer = await file.arrayBuffer();
    if (!buffer || buffer.byteLength === 0) {
      continue;
    }
    payloads.push({
      filename: file.name,
      content_base64: arrayBufferToBase64(buffer),
    });
  }
  return payloads;
}

export function importAcceptValue() {
  return '.txt,.md,.markdown,.json,.csv,.tsv,.html,.htm,.xml,.docx,.pdf';
}

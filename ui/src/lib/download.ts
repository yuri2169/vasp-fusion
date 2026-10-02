/** Hand the officer a file made in the browser (a graph picture, a GraphML export). */
export function downloadUrl(filename: string, url: string) {
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.rel = 'noopener'
  document.body.append(a)
  a.click()
  a.remove()
}

export function downloadText(filename: string, text: string, mime: string) {
  const url = URL.createObjectURL(new Blob([text], { type: mime }))
  downloadUrl(filename, url)
  // The click has started the download by now; the URL can go on the next tick.
  setTimeout(() => URL.revokeObjectURL(url), 0)
}

// Prints the text Vision finds in each image: one JSON line per image, {"path": ..., "lines": [...]}.
// Built once by reel/check.py into ~/.cache/demo-reel/ocr; usage: ocr <image>...
import Foundation
import Vision

for path in CommandLine.arguments.dropFirst() {
    var lines: [String] = []
    let request = VNRecognizeTextRequest { req, _ in
        for case let obs as VNRecognizedTextObservation in req.results ?? [] {
            if let top = obs.topCandidates(1).first { lines.append(top.string) }
        }
    }
    request.recognitionLevel = .accurate
    request.usesLanguageCorrection = false
    let handler = VNImageRequestHandler(url: URL(fileURLWithPath: path))
    try? handler.perform([request])
    let data = try! JSONSerialization.data(withJSONObject: ["path": path, "lines": lines])
    print(String(data: data, encoding: .utf8)!)
}

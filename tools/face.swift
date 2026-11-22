// Prints the largest face Vision finds in each image as JSON: {"path":..., "face":[x,y,w,h]} in
// 0..1 image coordinates with the origin at the top left, or "face": null.
// Built once by reel/narrate.py into ~/.cache/demo-reel/face; usage: face <image>...
import Foundation
import Vision

for path in CommandLine.arguments.dropFirst() {
    var best: [Double]? = nil
    let request = VNDetectFaceRectanglesRequest { req, _ in
        let faces = (req.results as? [VNFaceObservation]) ?? []
        if let f = faces.max(by: { $0.boundingBox.width * $0.boundingBox.height < $1.boundingBox.width * $1.boundingBox.height }) {
            let b = f.boundingBox
            best = [Double(b.minX), Double(1 - b.maxY), Double(b.width), Double(b.height)]
        }
    }
    try? VNImageRequestHandler(url: URL(fileURLWithPath: path)).perform([request])
    let obj: [String: Any] = ["path": path, "face": best as Any? ?? NSNull()]
    print(String(data: try! JSONSerialization.data(withJSONObject: obj), encoding: .utf8)!)
}

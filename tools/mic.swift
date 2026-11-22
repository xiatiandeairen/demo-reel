// Records the default microphone with AVAudioEngine into a CAF file until a line arrives on stdin.
// Prints "recording" once audio flows, so the caller can time-stamp the start.
// Built once by reel/narrate.py into ~/.cache/demo-reel/mic. ffmpeg's avfoundation audio capture
// clicked at every 4096-sample buffer boundary on this Mac (every 85 ms); this path does not.
import AVFoundation
import Foundation

let out = URL(fileURLWithPath: CommandLine.arguments[1])
let engine = AVAudioEngine()
let input = engine.inputNode
let format = input.outputFormat(forBus: 0)
let file = try AVAudioFile(forWriting: out, settings: format.settings, commonFormat: .pcmFormatFloat32, interleaved: false)
var announced = false
input.installTap(onBus: 0, bufferSize: 4096, format: format) { buffer, _ in
    try? file.write(from: buffer)
    if !announced { announced = true; print("recording"); fflush(stdout) }
}
try engine.start()
_ = readLine()
engine.stop()
input.removeTap(onBus: 0)

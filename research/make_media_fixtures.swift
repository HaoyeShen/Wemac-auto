// Small local fixtures derived from the user-provided image.
// No WeChat access or network operations; uses macOS media encoders only.
import Foundation
import CoreGraphics
import ImageIO
import AVFoundation
import CoreVideo
import UniformTypeIdentifiers

let root = URL(fileURLWithPath: FileManager.default.currentDirectoryPath).appendingPathComponent("research/fixtures")
guard CommandLine.arguments.count == 2 else {
    fatalError("Usage: swift research/make_media_fixtures.swift /absolute/path/to/source.png")
}
try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
let input = URL(fileURLWithPath: CommandLine.arguments[1])
guard let source = CGImageSourceCreateWithURL(input as CFURL, nil),
      let original = CGImageSourceCreateImageAtIndex(source, 0, nil) else { fatalError("Cannot read source image") }
let width = 320, height = 240
func frame(_ index: Int) -> CGImage {
    let context = CGContext(data: nil, width: width, height: height, bitsPerComponent: 8,
                            bytesPerRow: width * 4, space: CGColorSpaceCreateDeviceRGB(),
                            bitmapInfo: CGImageAlphaInfo.premultipliedFirst.rawValue)!
    context.setFillColor(CGColor(gray: 1, alpha: 1))
    context.fill(CGRect(x: 0, y: 0, width: width, height: height))
    let inset = CGFloat(index % 2 == 0 ? 0 : 8)
    context.draw(original, in: CGRect(x: inset, y: inset, width: CGFloat(width)-2*inset, height: CGFloat(height)-2*inset))
    return context.makeImage()!
}
let gifURL = root.appendingPathComponent("test.gif")
guard let gif = CGImageDestinationCreateWithURL(gifURL as CFURL, UTType.gif.identifier as CFString, 2, nil) else { fatalError("GIF writer failed") }
CGImageDestinationSetProperties(gif, [kCGImagePropertyGIFDictionary:[kCGImagePropertyGIFLoopCount:0]] as CFDictionary)
for i in 0..<2 {
    CGImageDestinationAddImage(gif, frame(i), [kCGImagePropertyGIFDictionary:[kCGImagePropertyGIFDelayTime:0.5]] as CFDictionary)
}
guard CGImageDestinationFinalize(gif) else { fatalError("GIF finalize failed") }
let thumbURL = root.appendingPathComponent("test-thumb.jpg")
let jpeg = CGImageDestinationCreateWithURL(thumbURL as CFURL, UTType.jpeg.identifier as CFString, 1, nil)!
CGImageDestinationAddImage(jpeg, frame(0), [kCGImageDestinationLossyCompressionQuality:0.6] as CFDictionary)
guard CGImageDestinationFinalize(jpeg) else { fatalError("JPEG finalize failed") }

let movieURL = root.appendingPathComponent("test.mp4")
if FileManager.default.fileExists(atPath: movieURL.path) { try FileManager.default.removeItem(at: movieURL) }
let writer = try AVAssetWriter(outputURL: movieURL, fileType: .mp4)
let settings: [String:Any] = [AVVideoCodecKey:AVVideoCodecType.h264, AVVideoWidthKey:width, AVVideoHeightKey:height]
let video = AVAssetWriterInput(mediaType:.video, outputSettings:settings)
let adaptor = AVAssetWriterInputPixelBufferAdaptor(assetWriterInput:video, sourcePixelBufferAttributes:[
    kCVPixelBufferPixelFormatTypeKey as String:kCVPixelFormatType_32ARGB,
    kCVPixelBufferWidthKey as String:width, kCVPixelBufferHeightKey as String:height])
writer.add(video)
guard writer.startWriting() else { fatalError("Video writer failed: \(String(describing: writer.error))") }
writer.startSession(atSourceTime:.zero)
for i in 0..<20 {
    let deadline = Date().addingTimeInterval(10)
    while !video.isReadyForMoreMediaData && Date()<deadline { Thread.sleep(forTimeInterval:0.01) }
    guard video.isReadyForMoreMediaData else { fatalError("Video writer timeout") }
    var buffer: CVPixelBuffer?
    guard CVPixelBufferPoolCreatePixelBuffer(nil, adaptor.pixelBufferPool!, &buffer)==kCVReturnSuccess,
          let pixel = buffer else { fatalError("Pixel buffer failed") }
    CVPixelBufferLockBaseAddress(pixel, [])
    let context = CGContext(data:CVPixelBufferGetBaseAddress(pixel), width:width, height:height, bitsPerComponent:8,
                            bytesPerRow:CVPixelBufferGetBytesPerRow(pixel), space:CGColorSpaceCreateDeviceRGB(),
                            bitmapInfo:CGImageAlphaInfo.noneSkipFirst.rawValue)!
    context.draw(frame(i/5), in:CGRect(x:0,y:0,width:width,height:height))
    CVPixelBufferUnlockBaseAddress(pixel, [])
    guard adaptor.append(pixel, withPresentationTime:CMTime(value:Int64(i),timescale:10)) else { fatalError("Video append failed") }
}
video.markAsFinished()
let done = DispatchSemaphore(value:0)
writer.finishWriting { done.signal() }
guard done.wait(timeout:.now()+30) == .success, writer.status == .completed else { fatalError("Video finalize failed") }
for path in [gifURL,thumbURL,movieURL] { print(path.path, (try Data(contentsOf:path)).count) }

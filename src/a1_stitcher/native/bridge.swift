// Independent Metal compute bridge. Buffers live until the command completes.
import Foundation
import Metal

final class Renderer {
    let device: MTLDevice
    let queue: MTLCommandQueue
    let pipeline: MTLComputePipelineState
    var buffers: [Int: MTLBuffer] = [:]
    init(_ source: String) throws {
        guard let d = MTLCreateSystemDefaultDevice(), let q = d.makeCommandQueue() else {
            throw NSError(domain: "A1Metal", code: 1, userInfo: [NSLocalizedDescriptionKey: "No Metal GPU available"])
        }
        device = d; queue = q
        let opts = MTLCompileOptions(); opts.fastMathEnabled = false
        let lib = try d.makeLibrary(source: source, options: opts)
        guard let f = lib.makeFunction(name: "stitch") else {
            throw NSError(domain: "A1Metal", code: 2)
        }
        pipeline = try d.makeComputePipelineState(function: f)
    }
    func buffer(_ i: Int, _ size: Int) throws -> MTLBuffer {
        if let b = buffers[i], b.length == size { return b }
        guard let b = device.makeBuffer(length: size, options: .storageModeShared) else {
            throw NSError(domain: "A1Metal", code: 3, userInfo: [NSLocalizedDescriptionKey: "GPU allocation failed"])
        }
        buffers[i] = b; return b
    }
}
func errorText(_ message: String, _ target: UnsafeMutablePointer<CChar>?, _ size: Int32) {
    if let target = target, size > 0 {
        message.withCString { _ = strlcpy(target, $0, Int(size)) }
    }
}
@_cdecl("a1_create")
public func create(_ source: UnsafePointer<CChar>, _ error: UnsafeMutablePointer<CChar>?, _ size: Int32) -> UnsafeMutableRawPointer? {
    do { return Unmanaged.passRetained(try Renderer(String(cString: source))).toOpaque() }
    catch let e { errorText(e.localizedDescription, error, size); return nil }
}
@_cdecl("a1_destroy")
public func destroy(_ handle: UnsafeMutableRawPointer) {
    Unmanaged<Renderer>.fromOpaque(handle).release()
}
@_cdecl("a1_render")
public func render(_ handle: UnsafeMutableRawPointer, _ inputs: UnsafePointer<UnsafeRawPointer?>,
                   _ lengths: UnsafePointer<Int64>, _ output: UnsafeMutableRawPointer,
                   _ outputBytes: Int64, _ width: Int32, _ height: Int32,
                   _ metrics: UnsafeMutablePointer<Double>, _ error: UnsafeMutablePointer<CChar>?, _ size: Int32) -> Int32 {
    do {
        let r = Unmanaged<Renderer>.fromOpaque(handle).takeUnretainedValue()
        guard let cmd = r.queue.makeCommandBuffer(), let enc = cmd.makeComputeCommandEncoder() else { return 2 }
        enc.setComputePipelineState(r.pipeline)
        for i in 0..<5 {
            let b = try r.buffer(i, Int(lengths[i]))
            memcpy(b.contents(), inputs[i]!, Int(lengths[i]))
            enc.setBuffer(b, offset: 0, index: i)
        }
        let out = try r.buffer(5, Int(outputBytes))
        let missing = try r.buffer(6, 4); memset(missing.contents(), 0, 4)
        enc.setBuffer(out, offset: 0, index: 5); enc.setBuffer(missing, offset: 0, index: 6)
        enc.dispatchThreads(MTLSize(width: Int(width), height: Int(height), depth: 1),
                            threadsPerThreadgroup: MTLSize(width: 16, height: 8, depth: 1))
        enc.endEncoding()
        let done = DispatchSemaphore(value: 0)
        cmd.addCompletedHandler { _ in done.signal() }
        cmd.commit()
        guard done.wait(timeout: .now() + 60) == .success else {
            errorText("Metal command timed out; discard this renderer", error, size); return 3
        }
        guard cmd.status == .completed else {
            errorText(cmd.error?.localizedDescription ?? "Metal command failed", error, size); return 4
        }
        memcpy(output, out.contents(), Int(outputBytes))
        metrics[0] = cmd.gpuEndTime - cmd.gpuStartTime
        metrics[1] = Double(missing.contents().load(as: UInt32.self))
        return 0
    } catch let e { errorText(e.localizedDescription, error, size); return 1 }
}
@_cdecl("a1_device_name")
public func deviceName(_ handle: UnsafeMutableRawPointer, _ target: UnsafeMutablePointer<CChar>?, _ size: Int32) {
    errorText(Unmanaged<Renderer>.fromOpaque(handle).takeUnretainedValue().device.name, target, size)
}

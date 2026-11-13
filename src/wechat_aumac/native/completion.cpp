// ABI bridge for the observed macOS 4.2.0 completion signature.
// Keep completion native: no JavaScript callback or script-lifetime dependency.
#include <atomic>
#include <cstddef>
#include <functional>
#include <new>
#include <utility>

using Completion = std::function<bool(void* const&, const int&, const int&)>;
static std::atomic<unsigned long long> completed{0};
static std::atomic<unsigned long long> failed{0};
static Completion make_completion() {
    return [](void* const&, const int& error_type, const int& error_code) noexcept {
        completed.fetch_add(1, std::memory_order_relaxed);
        if (error_type != 0 || error_code != 0)
            failed.fetch_add(1, std::memory_order_relaxed);
        // Observed caller deletes the scene when this returns true.
        return true;
    };
}
extern "C" {
std::size_t aumac_completion_size() noexcept { return sizeof(Completion); }
std::size_t aumac_completion_alignment() noexcept { return alignof(Completion); }
void aumac_completion_construct(void* storage) {
    ::new (storage) Completion(make_completion());
}
void aumac_completion_destroy(void* storage) noexcept {
    static_cast<Completion*>(storage)->~Completion();
}
unsigned long long aumac_completion_count() noexcept { return completed.load(); }
unsigned long long aumac_completion_failures() noexcept { return failed.load(); }
bool aumac_completion_selftest() {
    auto original = make_completion();
    Completion copied(original);
    Completion moved(std::move(copied));
    void* scene = nullptr;
    const int zero = 0;
    return original(scene, zero, zero) && moved(scene, zero, zero);
}
}

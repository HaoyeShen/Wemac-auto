#include <cassert>
#include <cstddef>
#include <functional>
#include <new>
#include <utility>
extern "C" {
std::size_t aumac_completion_size() noexcept;
std::size_t aumac_completion_alignment() noexcept;
void aumac_completion_construct(void*);
void aumac_completion_destroy(void*) noexcept;
unsigned long long aumac_completion_count() noexcept;
unsigned long long aumac_completion_failures() noexcept;
}
using Callback = std::function<bool(void* const&, const int&, const int&)>;
int main() {
    assert(aumac_completion_size() == sizeof(Callback));
    assert(aumac_completion_alignment() == alignof(Callback));
    alignas(Callback) unsigned char storage[sizeof(Callback)];
    aumac_completion_construct(storage);
    Callback copy(*reinterpret_cast<Callback*>(storage));
    aumac_completion_destroy(storage);
    // The task's copy must outlive the temporary passed to the submitter.
    Callback pending(std::move(copy));
    void* scene = nullptr;
    const int zero = 0, error = -4;
    const auto before = aumac_completion_count();
    assert(pending(scene, zero, zero));
    assert(aumac_completion_count() == before + 1);
    const auto failures = aumac_completion_failures();
    assert(pending(scene, zero, error));
    assert(aumac_completion_failures() == failures + 1);
    // Reproduce the original failure safely outside WeChat.
    bool threw = false;
    try { Callback empty; empty(scene, zero, zero); }
    catch (const std::bad_function_call&) { threw = true; }
    assert(threw);
}

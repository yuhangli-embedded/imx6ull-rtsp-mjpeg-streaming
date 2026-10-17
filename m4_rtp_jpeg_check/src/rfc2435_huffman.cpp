#include "lp2/rfc2435_huffman.hpp"
#include "jpeg_standard_codebooks.hpp"

#include <array>
#include <stdexcept>

namespace lp2 {
namespace {

// A canonical codebook is the internal representation, not a DHT wire blob.
// Both matching and serialization work from these bounded semantic records.
struct Codeword {
    unsigned int bits;
    unsigned char length;
    unsigned char symbol;
};
struct Codebook {
    unsigned char selector;
    std::size_t size;
    std::array<Codeword, 162> words;
};

unsigned int hex_digit(char value)
{
    if (value >= '0' && value <= '9') return static_cast<unsigned int>(value - '0');
    if (value >= 'a' && value <= 'f') return static_cast<unsigned int>(value - 'a' + 10);
    throw std::logic_error("Invalid standard parameter digit");
}

struct Catalog {
    std::array<Codebook, 4> tables;
    Catalog()
    {
        for (std::size_t t = 0; t < tables.size(); ++t) {
            Codebook& book = tables[t];
            const jpeg_parameters::LengthGroups& source = jpeg_parameters::standard[t];
            book.selector = source.selector;
            book.size = 0;
            unsigned int next_code = 0;
            std::array<bool, 256> used = {{false}};
            for (unsigned int length = 1; length <= 16; ++length) {
                const char* row = source.symbols_at_length[length - 1];
                while (*row != '\0') {
                    if (row[1] == '\0' || book.size == book.words.size() ||
                        next_code >= (1u << length))
                        throw std::logic_error("Invalid standard codebook");
                    const unsigned char symbol = static_cast<unsigned char>(
                        hex_digit(row[0]) * 16 + hex_digit(row[1]));
                    if (used[symbol]) throw std::logic_error("Duplicate standard symbol");
                    used[symbol] = true;
                    book.words[book.size++] = Codeword{
                        next_code++, static_cast<unsigned char>(length), symbol};
                    row += 2;
                }
                next_code <<= 1;
            }
            if (book.size != ((book.selector & 0x10) ? 162u : 12u))
                throw std::logic_error("Invalid standard symbol count");
        }
    }
};

const Catalog& catalog()
{
    // C++11 thread-safe initialization; bounded storage and no per-frame allocation.
    static const Catalog value;
    return value;
}

} // namespace

bool rfc2435_huffman_match(std::uint8_t table_class, std::uint8_t id,
                           const unsigned char* counts,
                           const unsigned char* symbols,
                           std::size_t symbol_count)
{
    if (table_class > 1 || id > 1 || counts == nullptr || symbols == nullptr)
        return false;
    const Codebook& expected = catalog().tables[id * 2 + table_class];
    if (symbol_count != expected.size) return false;

    // Validate the whole length histogram before reading any symbol.
    std::size_t total = 0;
    for (std::size_t i = 0; i < 16; ++i) total += counts[i];
    if (total != symbol_count) return false;

    std::size_t ordinal = 0;
    unsigned int code = 0;
    for (unsigned int length = 1; length <= 16; ++length) {
        if (code + counts[length - 1] > (1u << length)) return false;
        for (unsigned int n = 0; n < counts[length - 1]; ++n) {
            const Codeword& reference = expected.words[ordinal];
            if (reference.length != length || reference.bits != code ||
                reference.symbol != symbols[ordinal])
                return false;
            ++ordinal;
            ++code;
        }
        code <<= 1;
    }
    return ordinal == expected.size;
}

void append_rfc2435_huffman_markers(std::vector<unsigned char>& jpeg)
{
    // Assemble a complete bounded image first; append preserves caller prefix.
    std::array<unsigned char, 432> wire = {{0}};
    std::size_t cursor = 0;
    for (const Codebook& book : catalog().tables) {
        const unsigned int segment_length = static_cast<unsigned int>(19 + book.size);
        wire[cursor++] = 0xff;
        wire[cursor++] = 0xc4;
        wire[cursor++] = static_cast<unsigned char>(segment_length >> 8);
        wire[cursor++] = static_cast<unsigned char>(segment_length & 0xff);
        wire[cursor++] = book.selector;
        const std::size_t histogram = cursor;
        cursor += 16;
        for (std::size_t i = 0; i < book.size; ++i) {
            ++wire[histogram + book.words[i].length - 1];
            wire[cursor++] = book.words[i].symbol;
        }
    }
    if (cursor != wire.size()) throw std::logic_error("Unexpected DHT image size");
    jpeg.insert(jpeg.end(), wire.begin(), wire.end());
}

} // namespace lp2

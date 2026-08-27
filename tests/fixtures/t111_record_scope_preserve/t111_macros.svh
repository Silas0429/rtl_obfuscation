// No identifier of the design is written in any comment here, so a byte search
// for one finds only real code.

// A macro-generated aggregate field has no source-backed physical declaration
// of its own, so the aggregate that uses it is the one struct record in this
// fixture without complete binding evidence.
`define T111_FIELD(name) logic name

// Models the production `ASSERT_..._IF(..., expr, ...)` shape: the member
// accesses live in the macro *argument*, so their physical tokens exist only at
// the call site and have to be recovered from the expansion before they can be
// anchored.
`define T111_CHECK(dst, expr) assign dst = (expr)

// The assigned signal name below lives in the macro *body*, so every expansion
// shares one physical token: two expansions in two modules give one physical
// range two semantic meanings.
`define T111_BODY_ASSIGN(src) assign t111_shared_body = src

`define T100_CONTEXT_PARAM(NAME, VALUE) localparam int NAME = VALUE;

interface t100_context_if;
    `T100_CONTEXT_PARAM(T100_CONTEXT_LIMIT, 4)
endinterface

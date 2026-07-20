module t033_child #(
    parameter int WIDTH = 8
) (
    input  logic [WIDTH-1:0] data,
    output logic [WIDTH-1:0] q,
    t033_bus_if bus
);
    localparam int CHILD_LOCAL = WIDTH + 1;
    logic [WIDTH-1:0] child_signal;
    enum logic [1:0] {CHILD_IDLE, CHILD_BUSY} child_state;
    typedef logic [3:0] child_word_t;
    typedef struct packed {
        logic [1:0] field;
    } child_t;
    typedef union packed {
        logic [3:0] raw;
        logic [3:0] lane;
    } child_union_t;
    child_t child_value;
    child_union_t child_union;
    child_word_t child_word;
    t033_shared_t shared_value;
    function automatic logic [WIDTH-1:0] child_fn(
        input logic [WIDTH-1:0] value
    );
        child_fn = value;
    endfunction
    task automatic child_task(input logic [WIDTH-1:0] value);
        child_signal = value;
    endtask
    for (genvar child_index = 0; child_index < 4; child_index++) begin : child_generate
        always_comb child_word = child_signal[3:0];
    end
    always_comb child_state = CHILD_BUSY;
    assign child_signal = data;
    assign shared_value.valid = bus.valid;
    assign child_union.raw = child_word;
    assign q = child_signal;
endmodule

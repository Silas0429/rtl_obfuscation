module fifo_storage #(
    parameter int DATA_WIDTH = 8,
    parameter int DEPTH = 4,
    parameter int ADDR_WIDTH = 2
) (
    input  logic                  clk,
    input  logic                  rst_n,
    input  logic                  write_en,
    input  logic                  read_en,
    input  logic [ADDR_WIDTH-1:0] write_addr,
    input  logic [ADDR_WIDTH-1:0] read_addr,
    input  logic [DATA_WIDTH-1:0] data,
    output logic [DATA_WIDTH-1:0] q
);
    typedef logic [DATA_WIDTH-1:0] word_t;

    typedef struct packed {
        logic valid;
        word_t payload;
    } fifo_entry_t;

    typedef union packed {
        logic [DATA_WIDTH:0] raw;
        fifo_entry_t         entry;
    } fifo_view_t;

    word_t       storage [0:DEPTH-1];
    word_t       normalized_data;
    fifo_view_t  view;
    logic [ADDR_WIDTH-1:0] next_write_addr;
    logic [DEPTH-1:0]      slot_valid;

    function automatic word_t extract_payload(
        input fifo_entry_t entry_value
    );
        extract_payload = entry_value.payload;
    endfunction

    function automatic logic [ADDR_WIDTH-1:0] next_addr(
        input logic [ADDR_WIDTH-1:0] value
    );
        if (value == DEPTH - 1) begin
            next_addr = '0;
        end else begin
            next_addr = value + 1'b1;
        end
    endfunction

    task automatic normalize_word(
        input  logic [DATA_WIDTH-1:0] data,
        output logic [DATA_WIDTH-1:0] result
    );
        result = data;
    endtask

    assign next_write_addr = next_addr(write_addr);

    for (genvar i = 0; i < DEPTH; i++) begin : g_word
        assign slot_valid[i] = storage[i][0];
    end

    always_comb begin
        normalize_word(data, normalized_data);
        if (read_en) begin
            q = storage[read_addr];
            view.raw = {1'b1, q};
            if (view.entry.valid) begin
                q = extract_payload(view.entry);
            end
        end else begin
            q = '0;
            view.raw = '0;
        end
    end

    always_ff @(posedge clk) begin
        if (!rst_n) begin
            for (int reset_index = 0; reset_index < DEPTH; reset_index++) begin
                storage[reset_index] <= '0;
            end
        end else if (write_en) begin
            storage[write_addr] <= normalized_data;
        end
    end
endmodule

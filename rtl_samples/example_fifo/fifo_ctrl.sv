module fifo_ctrl #(
    parameter int DATA_WIDTH = 8,
    parameter int DEPTH = 4,
    parameter int ADDR_WIDTH = 2
) (
    input  logic                  clk,
    input  logic                  rst_n,
    input  logic                  push,
    input  logic                  pop,
    input  logic [DATA_WIDTH-1:0] data,
    output logic [DATA_WIDTH-1:0] q,
    output logic                  full,
    output logic                  empty,
    output logic                  valid
);
    typedef enum logic [1:0] {
        EMPTY,
        PARTIAL,
        FULL
    } state_t;

    logic [ADDR_WIDTH-1:0] wr_ptr;
    logic [ADDR_WIDTH-1:0] rd_ptr;
    logic [ADDR_WIDTH:0]   count;
    logic                  write_en;
    logic                  read_en;
    logic [DATA_WIDTH-1:0] mem_q;
    logic [DEPTH-1:0]      debug_mask;
    state_t                state;

    assign full = (count == DEPTH);
    assign empty = (count == 0);
    assign write_en = push && !full;
    assign read_en = pop && !empty;
    assign valid = read_en;
    assign q = mem_q;

    fifo_storage #(
        .DATA_WIDTH(DATA_WIDTH),
        .DEPTH(DEPTH),
        .ADDR_WIDTH(ADDR_WIDTH)
    ) u_mem (
        .clk(clk),
        .rst_n(rst_n),
        .write_en(write_en),
        .read_en(read_en),
        .write_addr(wr_ptr),
        .read_addr(rd_ptr),
        .data(data),
        .q(mem_q)
    );

    for (genvar i = 0; i < DEPTH; i++) begin : g_probe
        assign debug_mask[i] = (wr_ptr == i);
    end

    always_comb begin
        case (count)
            0:     state = EMPTY;
            DEPTH: state = FULL;
            default: state = PARTIAL;
        endcase
    end

    always_ff @(posedge clk) begin
        if (!rst_n) begin
            wr_ptr <= '0;
            rd_ptr <= '0;
            count  <= '0;
        end else begin
            case ({write_en, read_en})
                2'b10: count <= count + 1'b1;
                2'b01: count <= count - 1'b1;
                default: count <= count;
            endcase

            if (write_en) begin
                if (wr_ptr == DEPTH - 1) begin
                    wr_ptr <= '0;
                end else begin
                    wr_ptr <= wr_ptr + 1'b1;
                end
            end

            if (read_en) begin
                if (rd_ptr == DEPTH - 1) begin
                    rd_ptr <= '0;
                end else begin
                    rd_ptr <= rd_ptr + 1'b1;
                end
            end
        end
    end
endmodule

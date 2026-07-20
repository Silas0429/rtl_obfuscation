module lowrisk_child (
    input  logic       clk,
    input  logic [3:0] data_i,
    output logic [3:0] data_o
);
    typedef logic [3:0] nibble_t;

    typedef union packed {
        logic [3:0] raw;
        nibble_t    nibbles;
    } view_t;

    typedef enum logic {
        IDLE,
        RUN
    } state_t;

    nibble_t working;
    view_t   view;
    state_t  state;
    logic [3:0] generated;

    function automatic nibble_t transform(input nibble_t value);
        transform = value ^ 4'ha;
    endfunction

    task automatic copy_value(
        input  nibble_t source,
        output nibble_t destination
    );
        destination = source;
    endtask

    always_comb begin
        copy_value(data_i, working);
        view.raw = transform(working);
        if (view.nibbles == 0)
            state = IDLE;
        else
            state = RUN;
    end

    for (genvar lane = 0; lane < 4; lane++) begin : g_lane
        assign generated[lane] = view.raw[lane];
    end

    always_ff @(posedge clk) begin
        data_o <= (state == RUN) ? generated : '0;
    end
endmodule

module unreachable_lowrisk_decoy;
    typedef logic decoy_word_t;
    typedef union packed {
        logic decoy_raw;
        logic decoy_bit;
    } decoy_view_t;
    typedef enum logic {
        DECOY_IDLE,
        DECOY_RUN
    } decoy_state_t;
    decoy_word_t decoy_value;
    decoy_view_t decoy_view;
    decoy_state_t decoy_state;

    function automatic logic decoy_function(input logic decoy_argument);
        decoy_function = decoy_argument;
    endfunction

    task automatic decoy_task(input logic decoy_source);
        decoy_value = decoy_source;
    endtask

    for (genvar decoy_lane = 0; decoy_lane < 4; decoy_lane++) begin : decoy_block
        always_comb begin
            decoy_task(decoy_function(decoy_value));
            decoy_view.decoy_raw = decoy_value;
            decoy_state = decoy_view.decoy_bit ? DECOY_RUN : DECOY_IDLE;
        end
    end
endmodule

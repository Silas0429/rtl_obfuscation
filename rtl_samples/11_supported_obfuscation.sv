module sample11_supported_obfuscation #(
    parameter int WIDTH = 4,
    parameter logic [3:0] XOR_MASK = 4'ha
) (
    input  logic [3:0] input_data,
    input  logic       mode_select,
    output logic [3:0] output_data,
    output wire  [3:0] generated_output
);

    localparam int ACTIVE_BITS = WIDTH;
    localparam logic [3:0] RESET_VALUE = '0;

    typedef enum logic [1:0] {
        STATE_IDLE,
        STATE_MASK,
        STATE_PASS
    } state_t;

    logic [3:0] generated_data;
    logic [3:0] function_result;
    reg   [3:0] selected_data;
    wire  [3:0] transformed_data;
    tri   [3:0] observed_data;
    wire        width_enabled;
    state_t current_state;

    function automatic void apply_mask(
        input logic [3:0] function_data
    );
        function_result = function_data ^ XOR_MASK;
    endfunction

    task automatic select_value(
        input  logic [3:0] task_data,
        input  logic       task_mode,
        output logic [3:0] task_result
    );
        if (task_mode) begin
            task_result = task_data;
        end else begin
            task_result = RESET_VALUE;
        end
    endtask

    for (genvar bit_index = 0; bit_index < 4; bit_index++) begin : generate_input
        assign generated_output[bit_index] = input_data[bit_index];
    end

    assign generated_data = generated_output;
    assign transformed_data = generated_data;
    assign observed_data = transformed_data;
    assign width_enabled = (ACTIVE_BITS == 4);

    always_comb begin
        apply_mask(observed_data);
        select_value(function_result, mode_select, selected_data);

        case (mode_select & width_enabled)
            1'b0: current_state = STATE_IDLE;
            1'b1: current_state = STATE_MASK;
            default: current_state = STATE_PASS;
        endcase

        case (current_state)
            STATE_IDLE: output_data = selected_data;
            STATE_MASK: output_data = selected_data ^ XOR_MASK;
            default:    output_data = RESET_VALUE;
        endcase
    end

endmodule

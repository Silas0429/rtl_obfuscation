// Sample 10: enum state type, next-state logic, and asynchronous reset.
module sample10_systemverilog_fsm (
    input  logic clock,
    input  logic reset_n,
    input  logic start,
    output logic busy
);

    typedef enum logic [1:0] {
        STATE_IDLE,
        STATE_RUN,
        STATE_DONE
    } state_type;

    state_type current_state;
    state_type next_state;
    logic      busy_next;

    always_comb begin
        next_state = current_state;
        busy_next = 1'b0;

        case (current_state)
            STATE_IDLE: begin
                if (start)
                    next_state = STATE_RUN;
            end
            STATE_RUN: begin
                busy_next = 1'b1;
                next_state = STATE_DONE;
            end
            STATE_DONE: begin
                next_state = STATE_IDLE;
            end
            default: begin
                next_state = STATE_IDLE;
            end
        endcase
    end

    always_ff @(posedge clock or negedge reset_n) begin
        if (!reset_n) begin
            current_state <= STATE_IDLE;
            busy <= 1'b0;
        end else begin
            current_state <= next_state;
            busy <= busy_next;
        end
    end

endmodule

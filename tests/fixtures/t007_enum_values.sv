// T007 fixture: combinational enum value usage.
module t007_enum_values (
    input  logic [1:0] selector,
    output logic       active
);

    typedef enum logic [1:0] {
        STATE_IDLE,
        STATE_RUN,
        STATE_DONE
    } state_type;

    state_type state;

    always_comb begin
        case (selector)
            2'd0:    state = STATE_IDLE;
            2'd1:    state = STATE_RUN;
            default: state = STATE_DONE;
        endcase
        active = (state == STATE_RUN);
    end

endmodule

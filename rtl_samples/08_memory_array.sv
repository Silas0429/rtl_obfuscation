// Sample 08: unpacked memory array, indexed read, and synchronous write.
module sample08_memory_array (
    input  logic       clock,
    input  logic       write_enable,
    input  logic [1:0] address,
    input  logic [7:0] write_data,
    output logic [7:0] read_data
);

    logic [7:0] data_memory [0:3];
    logic [7:0] selected_word;

    always_ff @(posedge clock) begin
        if (write_enable) begin
            data_memory[address] <= write_data;
        end
    end

    always_comb begin
        selected_word = data_memory[address];
    end

    assign read_data = selected_word;

endmodule

interface t108_shape_if;
    logic value;
    modport master(input value);
endinterface

typedef struct packed {
    logic first;
    logic second;
} t108_shape_t;

module t108_nonansi(clk, data_i, bus, data_o);
    input clk;
    input logic [3:0] data_i;
    t108_shape_if bus;
    output logic data_o;
    t108_shape_t local_s;
    assign local_s.first = data_i[0];
    assign data_o = local_s.second ^ bus.value ^ clk;
endmodule

module t108_ansi(
    input logic clk,
    input logic [3:0] data_i,
    t108_shape_if bus,
    output logic data_o
);
    t108_shape_t local_s;
    assign local_s.first = data_i[0];
    assign data_o = local_s.second ^ bus.value ^ clk;
endmodule

module t108_shape_top(input logic clk, output logic result);
    t108_shape_if bus0();
    t108_shape_if bus1();
    t108_ansi u_ansi(
        .clk(clk), .data_i(4'b0), .bus(bus0), .data_o(result)
    );
    t108_nonansi u_nonansi(
        .clk(clk), .data_i(4'b0), .bus(bus1), .data_o(result)
    );
endmodule

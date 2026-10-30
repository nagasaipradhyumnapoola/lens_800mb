// lens-observer-testapp for Linux: a synthetic GTK 4 window for observer tests (never a user window), run on a virtual
// display. Shows a title, a label, a multi-line text view and a password field holding a synthetic secret.
// stdin commands (UTF-8 lines; "\n" in the text means a line break): set <text> | title <text> | quit.
// Prints "ready" once the window is shown and "ok" after each command.
// Usage: lens-observer-testapp <title> <label> <text>
#include <gtk/gtk.h>
#include <iostream>
#include <string>

namespace {
GtkWidget* window=nullptr;GtkTextBuffer* buffer=nullptr;GMainLoop* loop=nullptr;
std::string unescape(std::string s){size_t p;while((p=s.find("\\n"))!=std::string::npos)s.replace(p,2,"\n");return s;}
gboolean on_input(GIOChannel* ch,GIOCondition,gpointer) {
    gchar* raw=nullptr;gsize n=0;
    if(g_io_channel_read_line(ch,&raw,&n,nullptr,nullptr)!=G_IO_STATUS_NORMAL||!raw){g_main_loop_quit(loop);return G_SOURCE_REMOVE;}
    std::string line(raw);g_free(raw);while(!line.empty()&&(line.back()=='\n'||line.back()=='\r'))line.pop_back();
    if(line.rfind("set ",0)==0){const auto t=unescape(line.substr(4));gtk_text_buffer_set_text(buffer,t.c_str(),-1);}
    else if(line.rfind("title ",0)==0)gtk_window_set_title(GTK_WINDOW(window),line.substr(6).c_str());
    else if(line=="quit"){g_main_loop_quit(loop);return G_SOURCE_REMOVE;}
    std::cout<<"ok"<<std::endl;return G_SOURCE_CONTINUE;
}
}

int main(int argc,char** argv) {
    if(argc<4){std::cerr<<"usage: lens-observer-testapp <title> <label> <text>\n";return 2;}
    gtk_init();loop=g_main_loop_new(nullptr,FALSE);
    window=gtk_window_new();gtk_window_set_title(GTK_WINDOW(window),argv[1]);gtk_window_set_default_size(GTK_WINDOW(window),640,420);
    GtkWidget* box=gtk_box_new(GTK_ORIENTATION_VERTICAL,8);
    gtk_box_append(GTK_BOX(box),gtk_label_new(argv[2]));
    GtkWidget* view=gtk_text_view_new();buffer=gtk_text_view_get_buffer(GTK_TEXT_VIEW(view));
    const auto text=unescape(argv[3]);gtk_text_buffer_set_text(buffer,text.c_str(),-1);gtk_widget_set_vexpand(view,TRUE);
    gtk_box_append(GTK_BOX(box),view);
    GtkWidget* secret=gtk_password_entry_new();gtk_editable_set_text(GTK_EDITABLE(secret),"Synthetic secret 4242");
    gtk_box_append(GTK_BOX(box),secret);
    gtk_window_set_child(GTK_WINDOW(window),box);gtk_window_present(GTK_WINDOW(window));
    // Ready once the accessibility tree has been published (shortly after the window is shown).
    g_timeout_add(1500,[](gpointer)->gboolean{std::cout<<"ready"<<std::endl;return G_SOURCE_REMOVE;},nullptr);
    GIOChannel* in=g_io_channel_unix_new(0);g_io_add_watch(in,static_cast<GIOCondition>(G_IO_IN|G_IO_HUP),on_input,nullptr);
    g_main_loop_run(loop);
    return 0;
}

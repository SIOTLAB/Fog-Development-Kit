// Credit to Lucas Clemente for the quic-go library and the examples posted
// within the repo. They were used, in part, to construct this program.

// We integrate this application into the FDK as an example of how an important,
// real-world application can run on top of the platform, such as an object
// detection system, with a small set of additions used for interacting with
// the FDK.

package main

import (
	"encoding/binary"
	"bufio"
	"context"
	"crypto/rand"
	"crypto/rsa"
	"crypto/tls"
	"crypto/x509"
	"encoding/pem"
	"os/exec"
	"os"
	"fmt"
	"io"
	// "log"
	"math/big"
	"sync"
	"time"
	// "strings"
	"strconv"

	quic "github.com/lucas-clemente/quic-go"
)

var wg sync.WaitGroup

// Set the QUIC connection timeout
var config = &quic.Config {
	IdleTimeout: 1000 * time.Second,
}

func runObjDetectApp(fn string, session quic.Session) error {
	// Run the object detection program and wait to completion
	cmd := exec.Command("python3", "objectdetection.py", fn)
	out, err := cmd.Output()
	fmt.Println("Output: ", string(out))
	if err != nil {
		return err
	}

	// Open another stream to the end-device
	stream, err := session.OpenStreamSync(context.Background())
	if err != nil {
		return err
	}	
	
	// Send the return code back to the end-device on the desired connection
	b := make([]byte, 4)
	if err != nil {
		if exitError, ok := err.(*exec.ExitError); ok {
			fmt.Println(exitError.ExitCode())
			binary.LittleEndian.PutUint32(b, uint32(exitError.ExitCode()))
		} else {
			binary.LittleEndian.PutUint32(b, uint32(0))
		}
	}

	// Cleanup stream
	stream.Write(b)
	stream.Close()
	return nil
}

// Start a server that echos all data on the first stream opened by the client
func startServer(addr string) error {
	// Accept a connection from a QUIC client
	listener, err := quic.ListenAddr(addr, generateTLSConfig(), config)
	if err != nil {
		return err
	}
	session, err := listener.Accept(context.Background())
	if err != nil {
		return err
	}

	i := 0
	for {
		// Accept an incomingstream
		stream, err := session.AcceptStream(context.Background())
		if err != nil {
			return err
		}
		
		// Network buffer
		stride := 1024
		buf := make([]byte, stride)

		// Create the file to write to
		fn := "pic" + strconv.Itoa(i) + ".jpg"
		fmt.Println(fn, "DONE")
		f, err := os.Create(fn)
		if err != nil {
			fmt.Println("Error opening file: ", err)
			panic(err)//return err
		}

		// Setup Writer
		w := bufio.NewWriter(f)

		// Read until end of data stream
		var n int
		for {
			n, err = io.ReadAtLeast(stream, buf, 1)
			if err != nil {
				fmt.Println("ERROR READING DATA: ", err)
			}
			fmt.Println("Read bytes: ", n)
			w.Write(buf)
			
			if n < stride {
				break
			}
		}
		
		// Cleanup file
		w.Flush()
		f.Close()

		// Create a thread that runs the object detection program and reports
		// the result of execution back to the end-device
		wg.Add(1)
		go func() {
			err = runObjDetectApp(fn, session)
			if err != nil {
				panic(err)
			}
			wg.Done()
		}()

		stream.Close()
		i++
	}

	return err
}

// Setup a bare-bones TLS config for the server
func generateTLSConfig() *tls.Config {
	key, err := rsa.GenerateKey(rand.Reader, 1024)
	if err != nil {
		panic(err)
	}
	template := x509.Certificate{SerialNumber: big.NewInt(1)}
	certDER, err := x509.CreateCertificate(rand.Reader, &template, &template, &key.PublicKey, key)
	if err != nil {
		panic(err)
	}
	keyPEM := pem.EncodeToMemory(&pem.Block{Type: "RSA PRIVATE KEY", Bytes: x509.MarshalPKCS1PrivateKey(key)})
	certPEM := pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: certDER})

	tlsCert, err := tls.X509KeyPair(certPEM, keyPEM)
	if err != nil {
		panic(err)
	}
	return &tls.Config{
		Certificates: []tls.Certificate{tlsCert},
		NextProtos:   []string{"quic-echo-example"},
	}
}

func main() {
	// Specify IP and port
	// NOTE: Must listen on 0.0.0.0 if running within a docker container, which
	// is the intention of this application.
	var ip = "0.0.0.0"
	var port = os.Getenv("PORT")
	var addr = string(ip) + ":" + port
	
	// Ensure IP and port are set.
	if len(ip) == 0 || len(port) == 0 {
		fmt.Println("FOG_IP and/or PORT not set. Exiting.")
		return
	}

	wg.Add(1)
	go func() {
		err := startServer(addr)
		if err != nil {
			panic(err)
		}
		wg.Done()
	}()

	wg.Wait()
}

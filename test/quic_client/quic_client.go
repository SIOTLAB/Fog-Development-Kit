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
	"crypto/tls"
	crand "crypto/rand"
	"crypto/rsa"
	"crypto/x509"
	"encoding/pem"
	"fmt"
	"io"
	"math/big"
	// mrand "math/rand"
	"os"
	"sync"
	// "strconv"
	"time"
	
	quic "github.com/lucas-clemente/quic-go"
)

var ip = os.Getenv("FOG_IP")
var port = os.Getenv("PORT")

var addr string
// var ports map[uint16]bool
var wg sync.WaitGroup
const message = "foobar"

// Config
var tlsConf = &tls.Config{
	InsecureSkipVerify: true,
	NextProtos:         []string{"quic-echo-example"},
}

// Config QUIC connectionto timeout after 120 idle seconds
var config = &quic.Config {
	IdleTimeout: 1000 * time.Second,
	HandshakeTimeout: 30 * time.Second,	
}

// We start a server echoing data on the first stream the client opens,
// then connect with a client, send the message, and wait for its receipt.
func main() {
	// Grab server IP and port, and ensure they exist
	if len(ip) == 0 || len(port) == 0 {
		fmt.Println("FOG_IP and/or PORT not set. Exiting.")
		return
	}
	
	// Startup
	addr = ip + ":" + port
	// ports[p] = true
	wg.Add(1)
	go func() {
		err := startClient()
		if err != nil {
			panic(err)
		}
		wg.Done()
	}()

	fmt.Println("Transmission Complete: waiting for responses...")
	wg.Wait()
	fmt.Println("All responses received. Exiting.")
}

func validateReturnCode(session quic.Session) error {
	stream, err := session.AcceptStream(context.Background())
	if err != nil {
		return err
	}
	
	// Wait for the return code from the server
	buf := make([]byte, 4)
	n, err := io.ReadFull(stream, buf)
	fmt.Println("Read bytes: ", n)
	if err != nil {
		if err != io.ErrUnexpectedEOF {
			fmt.Fprintln(os.Stderr, err)
		}
	}
	ret := binary.LittleEndian.Uint32(buf)

	// Determine if the object detection application finished successfully
	fmt.Print(os.Stderr, "Return Code: ", ret)
	if ret == 0 {
		fmt.Println(os.Stderr, "   (Success)")
	} else {
		fmt.Println(os.Stderr, "   (Failure fog-side)")
	}

	stream.Close()

	return nil
}

// Setup a bare-bones TLS config for the server
func generateTLSConfig() *tls.Config {
	key, err := rsa.GenerateKey(crand.Reader, 1024)
	if err != nil {
		panic(err)
	}
	template := x509.Certificate{SerialNumber: big.NewInt(1)}
	certDER, err := x509.CreateCertificate(crand.Reader, &template, &template, &key.PublicKey, key)
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

func startClient() error {
	// Connect to the server
	fmt.Println("Connecting to ", addr)
	session, err := quic.DialAddr(addr, tlsConf, config)
	if err != nil {
		return err
	}

	// PUT FILENAMES HERE
	fns := []string{"Picture.jpg", "dogs.jpg", "cat-and-dog.jpg"}

	for _, fn := range fns {
		stream, err := session.OpenStreamSync(context.Background())
		if err != nil {
			return err
		}

		// Network buffer
		stride := 1024
		buf := make([]byte, 0, stride)

		fn = os.Getenv("HOME") + "/fog-development-kit/test/quic_client/" + fn
		f, err := os.Open(fn)
		
		// Check errors
		if err != nil {
			return err	
		}

		// Setup file reader
		r := bufio.NewReader(f)
		
		// Read from the file
		counter := 0
		for {
			n, err := io.ReadFull(r, buf[:cap(buf)])
			buf = buf[:n]

			if err != nil {
				if err == io.EOF {
					break
				}
				if err != io.ErrUnexpectedEOF {
					fmt.Fprintln(os.Stderr, err)
					break
				}
			}

			fmt.Println("Sending bytes: ", n)
			counter += n

			// Send over the bytes
			// fmt.Println("Sending bytes...")
			_, err = stream.Write(buf)
			if err != nil {
				return err
			}

			time.Sleep(5 * time.Millisecond)
		}

		// Debug
		fmt.Println("Total sent bytes: ", counter)

		// Close the stream
		stream.Close()

		// Open a new stream back to the end-device
		wg.Add(1)
		go func() {
			err = validateReturnCode(session)
			if err != nil {
				panic(err)
			}
			wg.Done()
		}()
	}
	
	return nil
}
